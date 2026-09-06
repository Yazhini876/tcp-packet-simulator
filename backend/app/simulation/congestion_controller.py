"""Simplified TCP Reno-style congestion controller.

SIMULATION APPROXIMATION (documented per project rules): this models the
textbook slow-start / congestion-avoidance / fast-retransmit / fast-recovery
behavior popularized by TCP Reno. It does not reproduce any specific real
kernel's congestion control (e.g. CUBIC, BBR), and cwnd is tracked as a
float count of MSS-sized *segments* rather than bytes, which keeps the
growth formulas and the chart's Y-axis easy to reason about educationally.

Growth rules:
  - Slow start: cwnd += 1 segment per ACK (exponential per RTT).
  - Congestion avoidance: cwnd += 1/cwnd segments per ACK (~+1 per RTT,
    i.e. additive increase).
  - Fast retransmit (3 duplicate ACKs): ssthresh = cwnd / 2 (min 2),
    cwnd = ssthresh + 3 (fast recovery inflation for the 3 dup ACKs already
    received), phase -> FAST_RECOVERY.
  - While in fast recovery, further duplicate ACKs inflate cwnd by 1 each
    (classic Reno window inflation).
  - The ACK that finally covers the retransmitted segment deflates the
    window back to ssthresh and exits recovery into congestion avoidance.
  - Timeout: ssthresh = cwnd / 2 (min 2), cwnd = 1, phase -> SLOW_START.
"""
from __future__ import annotations

from app.models.congestion import CongestionEventType, CongestionPhase, CongestionState
from app.models.connection import TCPConfig
from app.models.events import CwndUpdatedEvent
from app.simulation.clock import SimulationClock
from app.simulation.event_bus import EventBus

MIN_CWND_SEGMENTS = 1.0
MIN_SSTHRESH_SEGMENTS = 2.0


class CongestionController:
    def __init__(self, config: TCPConfig, event_bus: EventBus, clock: SimulationClock) -> None:
        self._event_bus = event_bus
        self._clock = clock
        self.state = CongestionState(
            cwnd_segments=float(config.initial_cwnd_segments),
            ssthresh_segments=float(config.ssthresh_initial_segments),
            phase=CongestionPhase.SLOW_START,
        )

    @property
    def cwnd_segments(self) -> float:
        return self.state.cwnd_segments

    def on_new_ack(self, is_recovery_ack: bool = False) -> None:
        """Call when a non-duplicate ACK advances SND.UNA.

        `is_recovery_ack=True` should be passed exactly when this ACK is the
        one that finally acknowledges the segment that triggered fast
        retransmit -- i.e. it signals recovery is complete.
        """
        s = self.state
        event_type = CongestionEventType.GROWTH

        if s.phase == CongestionPhase.FAST_RECOVERY:
            if is_recovery_ack:
                s.cwnd_segments = s.ssthresh_segments
                s.phase = CongestionPhase.CONGESTION_AVOIDANCE
            else:
                # Partial ACK during recovery: treat as ordinary recovery
                # inflation reset is intentionally NOT applied here (kept
                # simple); segment-level partial-ack handling is out of
                # scope for this educational model.
                s.cwnd_segments += 1.0
        elif s.phase == CongestionPhase.SLOW_START:
            s.cwnd_segments += 1.0
            if s.cwnd_segments >= s.ssthresh_segments:
                s.phase = CongestionPhase.CONGESTION_AVOIDANCE
        else:  # CONGESTION_AVOIDANCE
            s.cwnd_segments += 1.0 / max(s.cwnd_segments, 1.0)

        s.round_no += 1
        self._record_and_publish(event_type)

    def on_duplicate_ack_during_recovery(self) -> None:
        """Classic Reno window inflation: each additional dup ACK received
        while already in fast recovery grows cwnd by one segment."""
        if self.state.phase != CongestionPhase.FAST_RECOVERY:
            return
        self.state.cwnd_segments += 1.0
        self._record_and_publish(CongestionEventType.GROWTH)

    def on_fast_retransmit(self) -> None:
        """Call when the 3rd duplicate ACK triggers a fast retransmit."""
        s = self.state
        s.ssthresh_segments = max(s.cwnd_segments / 2.0, MIN_SSTHRESH_SEGMENTS)
        s.cwnd_segments = s.ssthresh_segments + 3.0
        s.phase = CongestionPhase.FAST_RECOVERY
        s.round_no += 1
        self._record_and_publish(CongestionEventType.DUP_ACK_FAST_RETRANSMIT)

    def on_timeout(self) -> None:
        s = self.state
        s.ssthresh_segments = max(s.cwnd_segments / 2.0, MIN_SSTHRESH_SEGMENTS)
        s.cwnd_segments = MIN_CWND_SEGMENTS
        s.phase = CongestionPhase.SLOW_START
        s.round_no += 1
        self._record_and_publish(CongestionEventType.TIMEOUT)

    def _record_and_publish(self, event_type: CongestionEventType) -> None:
        now = self._clock.now_ms
        self.state.record(now, event=event_type)
        self._event_bus.publish(
            CwndUpdatedEvent(
                session_time_ms=now,
                cwnd_segments=self.state.cwnd_segments,
                ssthresh_segments=self.state.ssthresh_segments,
                phase=self.state.phase,
                cause=event_type,
            )
        )
