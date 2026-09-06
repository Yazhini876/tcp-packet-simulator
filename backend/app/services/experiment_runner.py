"""Runs one or more `ExperimentDefinition`s headlessly (no WebSocket, no
real-time pacing) and produces comparable `ExperimentResult`s.

Because each `SimulationSession` is fully self-contained with its own
seeded RNG, experiments can run either sequentially or concurrently with
identical results -- concurrency here is just a performance choice, not a
correctness one.
"""
from __future__ import annotations

import asyncio
import time
from typing import List

from app.models.experiment import ExperimentDefinition, ExperimentResult
from app.simulation.session import SimulationSession


def run_experiment_sync(definition: ExperimentDefinition) -> ExperimentResult:
    session = SimulationSession(
        network_conditions=definition.network_conditions,
        tcp_config=definition.tcp_config,
        seed=definition.seed,
    )

    from app.services.statistics_engine import StatisticsEngine

    stats_engine = StatisticsEngine()
    stats_engine.subscribe_to(session.event_bus)

    session.start()
    session.run_until_idle(max_events=20_000)
    if session.client_fsm.state.value == "ESTABLISHED":
        session.send_message(definition.message_payload)
        session.run_until_idle(max_events=50_000)
        session.close()
        session.run_until_idle(max_events=5_000)

    completed = session.is_closed and session.clock.now_ms <= definition.max_virtual_time_ms

    return ExperimentResult(
        definition=definition,
        final_statistics=stats_engine.stats,
        cwnd_history=session.client_congestion.state.history,
        duration_ms=session.clock.now_ms,
        completed=completed,
    )


async def run_experiments(definitions: List[ExperimentDefinition]) -> List[ExperimentResult]:
    """Run all definitions concurrently using worker threads, since the
    simulation itself is synchronous CPU-bound Python."""
    loop = asyncio.get_running_loop()
    tasks = [loop.run_in_executor(None, run_experiment_sync, d) for d in definitions]
    return await asyncio.gather(*tasks)
