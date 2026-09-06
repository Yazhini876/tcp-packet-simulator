"""Explain Mode: short, technically-accurate explanations attached to
noteworthy simulation events, shown in the UI only when the user has
Explain Mode enabled.

Kept as a pure function so it has no dependency on the live WebSocket
plumbing and can be unit tested directly.
"""
from __future__ import annotations

from typing import Optional

from app.models.events import (
    CwndUpdatedEvent,
    DupAckDetectedEvent,
    FastRetransmitTriggeredEvent,
    PacketLostEvent,
    PacketRetransmittedEvent,
    PacketSentEvent,
    SimulationEvent,
    StateChangedEvent,
    TimeoutOccurredEvent,
)
from app.models.events import ExplainNoteEvent
from app.models.packet import PacketType

_PACKET_TYPE_EXPLANATIONS = {
    PacketType.SYN: (
        "SYN sent",
        "TCP is initiating a connection. The SYN flag synchronizes sequence "
        "numbers and begins the three-way handshake.",
    ),
    PacketType.SYN_ACK: (
        "SYN-ACK sent",
        "The server acknowledges the client's SYN and simultaneously sends "
        "its own SYN, proposing its initial sequence number.",
    ),
    PacketType.FIN: (
        "FIN sent",
        "One side has no more data to send and is beginning an orderly "
        "connection termination.",
    ),
    PacketType.DATA: (
        "Data segment sent",
        "The application message has been split into MSS-sized segments, "
        "each carrying its own sequence number.",
    ),
}


def explain_for_event(event: SimulationEvent) -> Optional[ExplainNoteEvent]:
    if isinstance(event, PacketSentEvent) and event.packet.packet_type in _PACKET_TYPE_EXPLANATIONS:
        title, text = _PACKET_TYPE_EXPLANATIONS[event.packet.packet_type]
        return ExplainNoteEvent(
            session_time_ms=event.session_time_ms,
            related_packet_type=event.packet.packet_type,
            title=title,
            explanation=text,
        )

    if isinstance(event, PacketLostEvent):
        reason_text = {
            "random_loss": "the configured packet loss probability",
            "buffer_overflow": "the simulated router buffer being full",
            "burst_loss": "an active Network Chaos burst-loss condition",
        }.get(event.reason or "random_loss", "the configured network conditions")
        return ExplainNoteEvent(
            session_time_ms=event.session_time_ms,
            related_packet_type=event.packet.packet_type,
            title="Packet lost",
            explanation=f"This packet never reached its destination, dropped due to {reason_text}.",
        )

    if isinstance(event, PacketRetransmittedEvent):
        cause_text = "a retransmission timeout expired" if event.cause == "timeout" else "3 duplicate ACKs were received"
        return ExplainNoteEvent(
            session_time_ms=event.session_time_ms,
            related_packet_type=event.packet.packet_type,
            title="Segment retransmitted",
            explanation=f"This segment was resent because {cause_text} without the expected acknowledgment.",
        )

    if isinstance(event, DupAckDetectedEvent):
        return ExplainNoteEvent(
            session_time_ms=event.session_time_ms,
            title="Duplicate ACK detected",
            explanation=(
                "The receiver re-sent the same acknowledgment number, signaling it "
                "received data out of order -- usually because an earlier segment "
                "was lost or delayed."
            ),
        )

    if isinstance(event, FastRetransmitTriggeredEvent):
        return ExplainNoteEvent(
            session_time_ms=event.session_time_ms,
            title="Fast retransmit triggered",
            explanation=(
                "Three duplicate ACKs is a strong enough signal of loss that TCP "
                "retransmits immediately, without waiting for the slower timeout."
            ),
        )

    if isinstance(event, TimeoutOccurredEvent):
        return ExplainNoteEvent(
            session_time_ms=event.session_time_ms,
            title="Retransmission timeout",
            explanation=(
                "No acknowledgment arrived within the retransmission timeout (RTO), "
                "so TCP assumes the segment was lost, resends it, and reduces its "
                "congestion window to be conservative."
            ),
        )

    if isinstance(event, CwndUpdatedEvent) and event.cause is not None:
        phase_text = {
            "SLOW_START": "growing exponentially in Slow Start",
            "CONGESTION_AVOIDANCE": "growing linearly in Congestion Avoidance",
            "FAST_RECOVERY": "in Fast Recovery after a fast retransmit",
        }.get(event.phase.value, "adjusting")
        return ExplainNoteEvent(
            session_time_ms=event.session_time_ms,
            title="Congestion window updated",
            explanation=f"The congestion window is now {round(event.cwnd_segments, 2)} segments, {phase_text}.",
        )

    if isinstance(event, StateChangedEvent) and event.new_state.value == "ESTABLISHED":
        return ExplainNoteEvent(
            session_time_ms=event.session_time_ms,
            title="Connection established",
            explanation=(
                "The three-way handshake is complete. Both sides have exchanged "
                "and acknowledged initial sequence numbers -- data can now flow."
            ),
        )

    return None
