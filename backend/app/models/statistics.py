"""Live and final simulation statistics, produced by the StatisticsEngine
reducer (`services/statistics_engine.py`)."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.tcp_state import TCPState


class SimulationStatistics(BaseModel):
    # Packet counters
    packets_sent: int = 0
    packets_delivered: int = 0
    packets_lost: int = 0
    retransmissions: int = 0
    duplicate_acks: int = 0
    timeouts: int = 0
    fast_retransmits: int = 0

    # RTT (milliseconds)
    rtt_samples: List[float] = Field(default_factory=list)
    rtt_avg_ms: Optional[float] = None
    rtt_min_ms: Optional[float] = None
    rtt_max_ms: Optional[float] = None

    # Throughput / goodput, in bits per second, measured over elapsed
    # virtual time since the first packet was sent.
    throughput_bps: float = 0.0
    """Includes retransmitted bytes -- i.e. total bits successfully
    delivered to the wire's destination, divided by elapsed time."""
    goodput_bps: float = 0.0
    """Excludes retransmitted duplicate bytes -- i.e. unique application
    payload bytes successfully delivered, divided by elapsed time."""

    bytes_delivered_total: int = 0
    bytes_delivered_unique: int = 0

    packet_loss_rate_percent: float = 0.0

    # Congestion / state snapshot
    current_cwnd_segments: float = 0.0
    current_ssthresh_segments: float = 0.0
    current_state_client: TCPState = TCPState.CLOSED
    current_state_server: TCPState = TCPState.CLOSED

    elapsed_ms: float = 0.0

    def add_rtt_sample(self, rtt_ms: float) -> None:
        self.rtt_samples.append(rtt_ms)
        self.rtt_min_ms = min(self.rtt_samples)
        self.rtt_max_ms = max(self.rtt_samples)
        self.rtt_avg_ms = sum(self.rtt_samples) / len(self.rtt_samples)

    def recompute_rates(self) -> None:
        if self.packets_sent > 0:
            self.packet_loss_rate_percent = (
                self.packets_lost / self.packets_sent
            ) * 100.0
        if self.elapsed_ms > 0:
            elapsed_s = self.elapsed_ms / 1000.0
            self.throughput_bps = (self.bytes_delivered_total * 8) / elapsed_s
            self.goodput_bps = (self.bytes_delivered_unique * 8) / elapsed_s
