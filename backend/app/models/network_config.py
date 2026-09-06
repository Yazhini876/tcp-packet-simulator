"""Configuration for the network condition simulator (left panel + chaos mode)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class NetworkConditions(BaseModel):
    """Baseline, always-on network parameters."""

    packet_loss_percent: float = Field(default=0.0, ge=0.0, le=100.0)
    latency_ms: float = Field(default=50.0, ge=0.0, le=5000.0)
    jitter_ms: float = Field(default=10.0, ge=0.0, le=1000.0)
    bandwidth_kbps: float = Field(default=10_000.0, ge=1.0, le=1_000_000.0,
                                   description="e.g. 10_000 kbps = 10 Mbps")
    buffer_size_kb: float = Field(default=64.0, ge=1.0, le=100_000.0)
    reorder_probability_percent: float = Field(default=0.0, ge=0.0, le=100.0)


class ChaosConditions(BaseModel):
    """Optional, user-toggleable extra conditions layered on top of
    `NetworkConditions` while a simulation is running (Network Chaos Mode).

    Each flag can be flipped independently and takes effect on the next
    packet transmitted -- it does not retroactively alter in-flight packets.
    """

    high_latency_enabled: bool = False
    high_latency_multiplier: float = Field(default=4.0, ge=1.0, le=20.0)

    random_burst_loss_enabled: bool = False
    burst_loss_size: int = Field(default=3, ge=1, le=20,
                                  description="Consecutive packets dropped once a burst triggers")
    burst_loss_trigger_percent: float = Field(default=5.0, ge=0.0, le=100.0)

    packet_bursts_enabled: bool = False
    """Sends several segments back-to-back with near-zero inter-departure
    delay, stressing bandwidth/buffer limits."""

    reordering_enabled: bool = False
    reorder_multiplier: float = Field(default=3.0, ge=1.0, le=10.0)

    bandwidth_cap_enabled: bool = False
    bandwidth_cap_kbps: float = Field(default=512.0, ge=1.0, le=1_000_000.0)

    buffer_overflow_enabled: bool = False
    """When enabled, exceeding `NetworkConditions.buffer_size_kb` of
    in-flight bytes causes newly transmitted packets to be dropped
    immediately (simulated router buffer overflow) rather than queued."""
