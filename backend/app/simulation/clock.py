"""Virtual simulation clock.

All simulation timing (RTT, RTO, latency, cwnd growth) is expressed in
*virtual milliseconds*. The clock is what maps virtual time to real
wall-clock delay when the engine is driven live (via asyncio.sleep in the
scheduler), scaled by a user-controlled speed multiplier.

Keeping this separate from the scheduler means: (a) unit tests can advance
virtual time synchronously with no real sleeping at all, and (b) "pause"
is just freezing virtual time, not tearing down any engine state.
"""
from __future__ import annotations


class SimulationClock:
    def __init__(self, speed_multiplier: float = 1.0) -> None:
        if speed_multiplier <= 0:
            raise ValueError("speed_multiplier must be > 0")
        self._virtual_ms: float = 0.0
        self._speed_multiplier: float = speed_multiplier
        self._paused: bool = False

    @property
    def now_ms(self) -> float:
        return self._virtual_ms

    @property
    def speed_multiplier(self) -> float:
        return self._speed_multiplier

    @property
    def is_paused(self) -> bool:
        return self._paused

    def set_speed(self, multiplier: float) -> None:
        if multiplier <= 0:
            raise ValueError("speed_multiplier must be > 0")
        self._speed_multiplier = multiplier

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def advance_to(self, virtual_ms: float) -> None:
        """Jump the clock forward to an absolute virtual time.

        Used by the scheduler when it pops the next due event; also used
        directly by synchronous unit tests that don't run the async loop.
        """
        if virtual_ms < self._virtual_ms:
            raise ValueError(
                f"Cannot move clock backwards: {virtual_ms} < {self._virtual_ms}"
            )
        self._virtual_ms = virtual_ms

    def real_delay_seconds(self, virtual_delta_ms: float) -> float:
        """Convert a virtual-time delta into a real-time `asyncio.sleep`
        duration, accounting for the speed multiplier."""
        if virtual_delta_ms <= 0:
            return 0.0
        return (virtual_delta_ms / 1000.0) / self._speed_multiplier
