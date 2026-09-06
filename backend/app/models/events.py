"""Simulation domain events.

These are emitted by the simulation engine onto the internal `EventBus`
(see `simulation/event_bus.py`). They are transport-agnostic: the engine
has no idea a WebSocket exists. `websocket/protocol.py` (Phase 3) wraps
each of these in a server->client envelope for the frontend.

Every event carries `session_time_ms`, the virtual simulation clock value
at the moment it occurred, so the frontend event log / packet capture /
charts all key off one consistent timeline instead of wall-clock time.
"""
from __future__ import annotations

import uuid
from typing import List, Literal, Optional, Union

from pydantic import BaseModel, Field

from app.models.congestion import CongestionEventType, CongestionPhase
from app.models.packet import Packet, PacketType, Role
from app.models.tcp_state import TCPState


class BaseEvent(BaseModel):
    session_time_ms: float


class StateChangedEvent(BaseEvent):
    type: Literal["state_changed"] = "state_changed"
    role: Role
    previous_state: TCPState
    new_state: TCPState
    trigger: str


class PacketSentEvent(BaseEvent):
    type: Literal["packet_sent"] = "packet_sent"
    packet: Packet


class PacketDeliveredEvent(BaseEvent):
    type: Literal["packet_delivered"] = "packet_delivered"
    packet: Packet


class PacketLostEvent(BaseEvent):
    type: Literal["packet_lost"] = "packet_lost"
    packet: Packet
    reason: Literal["random_loss", "buffer_overflow", "burst_loss"] = "random_loss"


class PacketRetransmittedEvent(BaseEvent):
    type: Literal["packet_retransmitted"] = "packet_retransmitted"
    packet: Packet
    original_packet_id: uuid.UUID
    cause: Literal["timeout", "fast_retransmit"]


class DupAckDetectedEvent(BaseEvent):
    type: Literal["dup_ack_detected"] = "dup_ack_detected"
    ack_no: int
    dup_count: int
    role: Role


class FastRetransmitTriggeredEvent(BaseEvent):
    type: Literal["fast_retransmit_triggered"] = "fast_retransmit_triggered"
    seq_no: int


class TimeoutOccurredEvent(BaseEvent):
    type: Literal["timeout_occurred"] = "timeout_occurred"
    seq_no: int
    retry_count: int


class CwndUpdatedEvent(BaseEvent):
    type: Literal["cwnd_updated"] = "cwnd_updated"
    cwnd_segments: float
    ssthresh_segments: float
    phase: CongestionPhase
    cause: Optional[CongestionEventType] = None


class ConnectionEstablishedEvent(BaseEvent):
    type: Literal["connection_established"] = "connection_established"


class ConnectionClosedEvent(BaseEvent):
    type: Literal["connection_closed"] = "connection_closed"


class StatsUpdatedEvent(BaseEvent):
    type: Literal["stats_updated"] = "stats_updated"
    # Kept loosely typed here; concrete shape lives in models/statistics.py
    # to avoid a circular import, and is attached by the emitter.
    stats: dict


class LogMessageEvent(BaseEvent):
    type: Literal["log_message"] = "log_message"
    message: str
    level: Literal["info", "warning", "error"] = "info"


class ExplainNoteEvent(BaseEvent):
    """Only emitted when Explain Mode is enabled."""

    type: Literal["explain_note"] = "explain_note"
    related_packet_type: Optional[PacketType] = None
    title: str
    explanation: str


SimulationEvent = Union[
    StateChangedEvent,
    PacketSentEvent,
    PacketDeliveredEvent,
    PacketLostEvent,
    PacketRetransmittedEvent,
    DupAckDetectedEvent,
    FastRetransmitTriggeredEvent,
    TimeoutOccurredEvent,
    CwndUpdatedEvent,
    ConnectionEstablishedEvent,
    ConnectionClosedEvent,
    StatsUpdatedEvent,
    LogMessageEvent,
    ExplainNoteEvent,
]
