"""Statistics engine: folds a stream of `SimulationEvent`s into
`SimulationStatistics`.

`reduce_event` is a pure function: `(stats, event) -> stats`, mutated and
returned in place. This is what makes it trivially testable (feed a
scripted list of events, assert final counters) and reusable both for a
live session (via `StatisticsEngine`, which subscribes to the session's
EventBus) and for headless Experiment Mode runs.

SIMULATION APPROXIMATION: goodput ("unique" bytes) is approximated as the
sum of payload bytes from *delivered, non-retransmission* DATA packets.
A byte-accurate accounting would need to track exact sequence-range
coverage to handle partial overlaps; that precision isn't necessary for
the educational goodput-vs-throughput comparison this tool is built to
demonstrate.
"""
from __future__ import annotations

from app.models.events import (
    CwndUpdatedEvent,
    DupAckDetectedEvent,
    FastRetransmitTriggeredEvent,
    PacketDeliveredEvent,
    PacketLostEvent,
    PacketRetransmittedEvent,
    PacketSentEvent,
    SimulationEvent,
    StateChangedEvent,
    TimeoutOccurredEvent,
)
from app.models.packet import Role
from app.models.statistics import SimulationStatistics
from app.simulation.event_bus import EventBus


def reduce_event(stats: SimulationStatistics, event: SimulationEvent) -> SimulationStatistics:
    if isinstance(event, PacketSentEvent):
        stats.packets_sent += 1

    elif isinstance(event, PacketDeliveredEvent):
        stats.packets_delivered += 1
        pkt = event.packet
        if pkt.rtt_ms is not None:
            stats.add_rtt_sample(pkt.rtt_ms)
        stats.bytes_delivered_total += pkt.payload_size
        if not pkt.is_retransmission:
            stats.bytes_delivered_unique += pkt.payload_size

    elif isinstance(event, PacketLostEvent):
        stats.packets_lost += 1

    elif isinstance(event, PacketRetransmittedEvent):
        stats.retransmissions += 1

    elif isinstance(event, DupAckDetectedEvent):
        stats.duplicate_acks += 1

    elif isinstance(event, TimeoutOccurredEvent):
        stats.timeouts += 1

    elif isinstance(event, FastRetransmitTriggeredEvent):
        stats.fast_retransmits += 1

    elif isinstance(event, CwndUpdatedEvent):
        stats.current_cwnd_segments = event.cwnd_segments
        stats.current_ssthresh_segments = event.ssthresh_segments

    elif isinstance(event, StateChangedEvent):
        if event.role == Role.CLIENT:
            stats.current_state_client = event.new_state
        else:
            stats.current_state_server = event.new_state

    stats.elapsed_ms = max(stats.elapsed_ms, event.session_time_ms)
    stats.recompute_rates()
    return stats


class StatisticsEngine:
    """Stateful wrapper: owns a `SimulationStatistics` instance and updates
    it automatically when subscribed to a session's `EventBus`."""

    def __init__(self) -> None:
        self.stats = SimulationStatistics()

    def subscribe_to(self, bus: EventBus) -> None:
        bus.subscribe(self._on_event)

    def _on_event(self, event: SimulationEvent) -> None:
        reduce_event(self.stats, event)
