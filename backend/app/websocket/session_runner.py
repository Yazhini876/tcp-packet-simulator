"""Drives one `SimulationSession` in real (wall-clock) time, translating
between the synchronous engine and the async WebSocket world.

Design: a single asyncio task (`run()`) owns the session's event loop. It
alternates between (a) waiting for either the next scheduled event's due
time or an incoming control command, whichever comes first, and (b)
processing exactly one scheduled event via `session.process_next()`. This
keeps all engine mutation on one task -- no locks needed -- while still
letting the frontend pause/resume/change speed/send data with low latency.
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, Optional

from app.models.connection import TCPConfig
from app.models.events import SimulationEvent
from app.models.network_config import ChaosConditions, NetworkConditions
from app.services.explain_mode import explain_for_event
from app.services.statistics_engine import StatisticsEngine
from app.simulation.session import SimulationSession
from app.websocket.protocol import (
    ClientMessage,
    CloseConnectionMsg,
    PauseSimulationMsg,
    ResetSimulationMsg,
    ResumeSimulationMsg,
    SendMessageMsg,
    SetSpeedMsg,
    StartSimulationMsg,
    ToggleChaosConditionMsg,
    ToggleExplainModeMsg,
    UpdateNetworkConfigMsg,
    UpdateTcpConfigMsg,
)

SendFn = Callable[[Dict[str, Any]], Awaitable[None]]

_IDLE_POLL_SECONDS = 0.2
"""How long to wait for a command when the scheduler has nothing queued
(e.g. before `start_simulation`, or after the connection fully closes)."""


class LiveSessionRunner:
    def __init__(self, session_factory: Callable[[], SimulationSession], send: SendFn) -> None:
        self._session_factory = session_factory
        self.session: SimulationSession = session_factory()
        self._send = send
        self._commands: "asyncio.Queue[ClientMessage]" = asyncio.Queue()
        self._explain_mode = False
        self.statistics = StatisticsEngine()
        self._outbox: list[SimulationEvent] = []
        """Events published synchronously by the engine during the current
        command/tick, buffered here and flushed in order (see `_flush`)
        rather than forwarded via fire-and-forget tasks -- that would race
        with the trailing stats_snapshot send below."""
        self._attach_subscriptions()
        self._stop = False

    def _attach_subscriptions(self) -> None:
        self.statistics.subscribe_to(self.session.event_bus)
        self.session.event_bus.subscribe(self._outbox.append)

    def enqueue(self, message: ClientMessage) -> None:
        self._commands.put_nowait(message)

    def stop(self) -> None:
        self._stop = True

    async def run(self) -> None:
        while not self._stop:
            # Drain any commands that are already waiting, applying them
            # immediately without spending a wait cycle.
            while not self._commands.empty():
                await self._apply_command(self._commands.get_nowait())

            if self.session.clock.is_paused:
                command = await self._wait_for_command_or_timeout(_IDLE_POLL_SECONDS)
                if command is not None:
                    await self._apply_command(command)
                continue

            next_due = self.session.scheduler.peek_next_time()
            if next_due is None:
                command = await self._wait_for_command_or_timeout(_IDLE_POLL_SECONDS)
                if command is not None:
                    await self._apply_command(command)
                continue

            delay_s = self.session.clock.real_delay_seconds(next_due - self.session.clock.now_ms)
            command = await self._wait_for_command_or_timeout(delay_s)
            if command is not None:
                await self._apply_command(command)
                continue  # re-evaluate before consuming the scheduled event

            self.session.process_next()
            await self._flush_outbox_and_stats()

    async def _wait_for_command_or_timeout(self, timeout_s: float) -> Optional[ClientMessage]:
        try:
            return await asyncio.wait_for(self._commands.get(), timeout=max(timeout_s, 0.0))
        except asyncio.TimeoutError:
            return None

    async def _flush_outbox_and_stats(self) -> None:
        """Send every event the engine published during the last
        synchronous call, strictly in publish order, then a fresh stats
        snapshot. Called after both `process_next()` (in `run()`) and
        engine-mutating commands (in `_apply_command`)."""
        pending = list(self._outbox)
        self._outbox.clear()
        for event in pending:
            await self._send(event.model_dump(mode="json"))
            if self._explain_mode:
                note = explain_for_event(event)
                if note is not None:
                    await self._send(note.model_dump(mode="json"))
        await self._send({"type": "stats_snapshot", "stats": self.statistics.stats.model_dump(mode="json")})

    async def _apply_command(self, message: ClientMessage) -> None:
        s = self.session
        if isinstance(message, StartSimulationMsg):
            s.start()
        elif isinstance(message, PauseSimulationMsg):
            s.clock.pause()
        elif isinstance(message, ResumeSimulationMsg):
            s.clock.resume()
        elif isinstance(message, ResetSimulationMsg):
            self._reset_session()
        elif isinstance(message, SetSpeedMsg):
            s.clock.set_speed(message.multiplier)
        elif isinstance(message, UpdateNetworkConfigMsg):
            merged = s.network_conditions.model_copy(update=message.payload)
            NetworkConditions.model_validate(merged.model_dump())  # re-validate bounds
            s.network_conditions = merged
            s.network_simulator.update_conditions(merged)
        elif isinstance(message, UpdateTcpConfigMsg):
            merged = s.tcp_config.model_copy(update=message.payload)
            TCPConfig.model_validate(merged.model_dump())
            s.tcp_config = merged
        elif isinstance(message, SendMessageMsg):
            s.send_message(message.payload)
        elif isinstance(message, CloseConnectionMsg):
            s.close()
        elif isinstance(message, ToggleChaosConditionMsg):
            if not hasattr(s.chaos_conditions, message.condition):
                raise ValueError(f"Unknown chaos condition: {message.condition}")
            setattr(s.chaos_conditions, message.condition, message.enabled)
            s.network_simulator.update_chaos(s.chaos_conditions)
        elif isinstance(message, ToggleExplainModeMsg):
            self._explain_mode = message.enabled
        await self._flush_outbox_and_stats()

    def _reset_session(self) -> None:
        old = self.session
        new_session = SimulationSession(
            network_conditions=old.network_conditions,
            chaos_conditions=ChaosConditions(**old.chaos_conditions.model_dump()),
            tcp_config=old.tcp_config,
        )
        self.session = new_session
        self.statistics = StatisticsEngine()
        self._outbox = []
        self._attach_subscriptions()
