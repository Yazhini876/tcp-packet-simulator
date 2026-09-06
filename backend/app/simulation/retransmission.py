"""Retransmission timeout (RTO) tracking and duplicate-ACK counting for a
single sending endpoint.

This manager owns the "is a segment considered lost yet?" decision --
either via RTO expiry (`check_timeouts`) or via the fast-retransmit dup-ACK
heuristic (`on_ack`). It does NOT decide whether a packet is *actually*
lost on the wire; that is the `NetworkSimulator`'s job. The two are
deliberately independent: a segment can time out even though it was
actually delivered late (e.g. due to high jitter), which is itself a
realistic and worth-teaching TCP behavior (spurious retransmission).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.models.connection import TCPConfig
from app.models.events import DupAckDetectedEvent, FastRetransmitTriggeredEvent, TimeoutOccurredEvent
from app.models.packet import Packet, Role
from app.simulation.clock import SimulationClock
from app.simulation.congestion_controller import CongestionController
from app.simulation.event_bus import EventBus


def segment_end_seq(packet: Packet) -> int:
    """The sequence number one past the last byte this segment consumes.

    SYN and FIN each consume one sequence number even with zero payload,
    matching standard TCP sequence-number accounting.
    """
    length = packet.payload_size
    if packet.flags.syn or packet.flags.fin:
        length += 1
    return packet.seq_no + length


@dataclass
class _InFlightEntry:
    packet: Packet
    rto_deadline_ms: float
    retry_count: int = 0


@dataclass
class TimeoutResult:
    entry_packet: Packet
    retry_count: int
    exceeded_max_retries: bool


class RetransmissionManager:
    def __init__(self, role: Role, config: TCPConfig, congestion: CongestionController,
                 event_bus: EventBus, clock: SimulationClock) -> None:
        self.role = role
        self._config = config
        self._congestion = congestion
        self._event_bus = event_bus
        self._clock = clock

        self._in_flight: Dict[uuid.UUID, _InFlightEntry] = {}
        self._last_ack_no: Optional[int] = None
        self._dup_ack_count: int = 0
        self._retransmitting_packet_id: Optional[uuid.UUID] = None
        """Tracks the packet id currently under fast-recovery, so we can
        detect the ACK that finally covers it and signal recovery exit."""
        self.should_fast_retransmit_packet: Optional[Packet] = None
        """Set by `on_ack` when a fast retransmit was just triggered; the
        caller should check this immediately after calling `on_ack` and
        clear it once handled."""

    @property
    def in_flight_count(self) -> int:
        return len(self._in_flight)

    def register_sent(self, packet: Packet) -> float:
        """Track `packet` as awaiting an ACK. Returns the RTO deadline
        (virtual ms) so the caller can also schedule a corresponding
        'rto_check' event -- the manager itself has no scheduler access."""
        deadline = self._clock.now_ms + self._config.retransmission_timeout_ms
        self._in_flight[packet.id] = _InFlightEntry(packet=packet, rto_deadline_ms=deadline)
        return deadline

    def cancel(self, packet_id: uuid.UUID) -> None:
        self._in_flight.pop(packet_id, None)

    def oldest_unacked(self) -> Optional[Packet]:
        if not self._in_flight:
            return None
        oldest = min(self._in_flight.values(), key=lambda e: e.packet.seq_no)
        return oldest.packet

    def on_ack(self, ack_no: int) -> List[uuid.UUID]:
        """Process an incoming ACK. Returns the list of packet ids that were
        fully acknowledged and removed from the in-flight set (empty if
        this was a duplicate ACK).

        May trigger a fast retransmit as a side effect once the duplicate
        ACK threshold is reached; the caller (session) should check
        `should_fast_retransmit` immediately after calling this.
        """
        self.should_fast_retransmit_packet: Optional[Packet] = None

        is_new_progress = self._last_ack_no is None or ack_no > self._last_ack_no

        if is_new_progress:
            acked_ids = [
                pid for pid, entry in self._in_flight.items()
                if segment_end_seq(entry.packet) <= ack_no
            ]
            is_recovery_ack = (
                self._retransmitting_packet_id is not None
                and self._retransmitting_packet_id in acked_ids
            )
            for pid in acked_ids:
                del self._in_flight[pid]

            if is_recovery_ack:
                self._retransmitting_packet_id = None

            if acked_ids:
                self._congestion.on_new_ack(is_recovery_ack=is_recovery_ack)

            self._last_ack_no = ack_no
            self._dup_ack_count = 0
            return acked_ids

        # ack_no == last_ack_no: only a "duplicate" if there is still
        # unacknowledged data outstanding (matches RFC 5681's definition).
        if self._in_flight:
            self._dup_ack_count += 1
            self._event_bus.publish(
                DupAckDetectedEvent(
                    session_time_ms=self._clock.now_ms,
                    ack_no=ack_no,
                    dup_count=self._dup_ack_count,
                    role=self.role,
                )
            )
            if self._dup_ack_count == self._config.dup_ack_threshold:
                self._trigger_fast_retransmit(ack_no)
            elif self._dup_ack_count > self._config.dup_ack_threshold:
                self._congestion.on_duplicate_ack_during_recovery()

        return []

    def _trigger_fast_retransmit(self, ack_no: int) -> None:
        target = self.oldest_unacked()
        if target is None:
            return
        self._retransmitting_packet_id = target.id
        self._congestion.on_fast_retransmit()
        self._event_bus.publish(
            FastRetransmitTriggeredEvent(session_time_ms=self._clock.now_ms, seq_no=target.seq_no)
        )
        self.should_fast_retransmit_packet = target
        # Reset its RTO so it isn't *also* timed out immediately after being
        # fast-retransmitted.
        if target.id in self._in_flight:
            self._in_flight[target.id].rto_deadline_ms = (
                self._clock.now_ms + self._config.retransmission_timeout_ms
            )

    def check_timeouts(self, now_ms: float) -> List[TimeoutResult]:
        """Return entries whose RTO has expired as of `now_ms`.

        For each expired entry, the congestion controller is notified
        (timeout -> cwnd reset) and its deadline/retry_count are updated
        in place so it isn't immediately reported as timed-out again next
        tick. The caller is responsible for actually resending the segment
        via the scheduler.
        """
        results: List[TimeoutResult] = []
        for entry in list(self._in_flight.values()):
            if entry.rto_deadline_ms <= now_ms:
                entry.retry_count += 1
                exceeded = entry.retry_count > self._config.max_retries
                self._congestion.on_timeout()
                self._event_bus.publish(
                    TimeoutOccurredEvent(
                        session_time_ms=now_ms,
                        seq_no=entry.packet.seq_no,
                        retry_count=entry.retry_count,
                    )
                )
                if not exceeded:
                    entry.rto_deadline_ms = now_ms + self._config.retransmission_timeout_ms
                results.append(
                    TimeoutResult(
                        entry_packet=entry.packet,
                        retry_count=entry.retry_count,
                        exceeded_max_retries=exceeded,
                    )
                )
                if exceeded:
                    self._in_flight.pop(entry.packet.id, None)
        return results

    def reset(self) -> None:
        self._in_flight.clear()
        self._last_ack_no = None
        self._dup_ack_count = 0
        self._retransmitting_packet_id = None
