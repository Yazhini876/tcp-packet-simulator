"""Congestion-control state models.

The congestion controller implements a simplified TCP Reno-style model:
slow start, congestion avoidance, fast retransmit / fast recovery, and
timeout-triggered reset. This is a well-established simplification, not a
claim of matching any specific real-world TCP implementation (e.g. CUBIC,
BBR) -- documented here and in the README.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class CongestionPhase(str, Enum):
    SLOW_START = "SLOW_START"
    CONGESTION_AVOIDANCE = "CONGESTION_AVOIDANCE"
    FAST_RECOVERY = "FAST_RECOVERY"


class CongestionEventType(str, Enum):
    GROWTH = "GROWTH"
    DUP_ACK_FAST_RETRANSMIT = "DUP_ACK_FAST_RETRANSMIT"
    TIMEOUT = "TIMEOUT"


class CongestionSample(BaseModel):
    """One point in the cwnd-over-time history, feeding the chart directly."""

    round_no: int
    time_ms: float
    cwnd_segments: float
    ssthresh_segments: float
    phase: CongestionPhase
    event: Optional[CongestionEventType] = None


class CongestionState(BaseModel):
    cwnd_segments: float
    ssthresh_segments: float
    phase: CongestionPhase = CongestionPhase.SLOW_START
    round_no: int = 0
    history: List[CongestionSample] = Field(default_factory=list)

    def record(self, time_ms: float, event: Optional[CongestionEventType] = None) -> None:
        self.history.append(
            CongestionSample(
                round_no=self.round_no,
                time_ms=time_ms,
                cwnd_segments=self.cwnd_segments,
                ssthresh_segments=self.ssthresh_segments,
                phase=self.phase,
                event=event,
            )
        )
