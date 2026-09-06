from __future__ import annotations

import random

import pytest

from app.models.connection import TCPConfig
from app.models.network_config import NetworkConditions
from app.simulation.session import SimulationSession


@pytest.fixture
def seeded_rng():
    return random.Random(42)


@pytest.fixture
def fast_tcp_config() -> TCPConfig:
    """Small MSS + short RTO so tests exercise multiple RTTs/timeouts
    quickly without needing huge messages or long waits."""
    return TCPConfig(
        mss_bytes=4,
        initial_cwnd_segments=1,
        retransmission_timeout_ms=200.0,
        max_retries=5,
        dup_ack_threshold=3,
        ssthresh_initial_segments=8,
        time_wait_ms=50.0,
    )


def make_session(
    *,
    seed: int = 1,
    loss_percent: float = 0.0,
    latency_ms: float = 20.0,
    jitter_ms: float = 0.0,
    tcp_config: TCPConfig | None = None,
) -> SimulationSession:
    conditions = NetworkConditions(
        packet_loss_percent=loss_percent,
        latency_ms=latency_ms,
        jitter_ms=jitter_ms,
        bandwidth_kbps=10_000.0,
        buffer_size_kb=64.0,
        reorder_probability_percent=0.0,
    )
    return SimulationSession(
        network_conditions=conditions,
        tcp_config=tcp_config or TCPConfig(retransmission_timeout_ms=300.0, time_wait_ms=50.0),
        seed=seed,
    )
