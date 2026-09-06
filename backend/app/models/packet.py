"""Packet-level data models for the TCP simulation engine.

A `Packet` is the single unit that flows through the simulator: the TCP
engine creates them, the network simulator decides their fate (delivered /
lost / reordered / delayed), and the statistics engine + UI consume the
resulting stream of state changes.

NOTE (simulation approximation): `checksum_valid` is always True in this
simulator. We do not model bit-level corruption, only loss, delay, jitter,
bandwidth limits and reordering. This is documented here and in the README
so the simulation is never mistaken for a byte-accurate TCP/IP stack.
"""
from __future__ import annotations

import uuid
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Role(str, Enum):
    """The two endpoints in every simulated connection."""

    CLIENT = "client"
    SERVER = "server"


class PacketType(str, Enum):
    """High-level classification used for UI coloring/filtering.

    This is derived from `PacketFlags` + payload size at construction time
    rather than being an independent source of truth, so a packet's type
    and its flags can never disagree.
    """

    SYN = "SYN"
    SYN_ACK = "SYN-ACK"
    ACK = "ACK"
    DATA = "DATA"
    DUP_ACK = "DUP-ACK"
    RETRANSMISSION = "RETRANSMISSION"
    FIN = "FIN"
    FIN_ACK = "FIN-ACK"
    RST = "RST"


class PacketStatus(str, Enum):
    """Lifecycle status of a packet within the simulation."""

    IN_FLIGHT = "IN_FLIGHT"
    DELIVERED = "DELIVERED"
    LOST = "LOST"
    RETRANSMITTED = "RETRANSMITTED"
    ACKED = "ACKED"


class PacketFlags(BaseModel):
    """TCP control bits relevant to this simulator.

    URG/PSH/ECE/CWR are intentionally omitted -- out of scope for the
    concepts this lab teaches (handshake, data transfer, loss/retransmit,
    congestion control, termination).
    """

    syn: bool = False
    ack: bool = False
    fin: bool = False
    rst: bool = False

    def as_label(self) -> str:
        """Human-readable flag string, e.g. 'SYN,ACK' -- used in the packet
        capture table and event log."""
        parts = []
        if self.syn:
            parts.append("SYN")
        if self.ack:
            parts.append("ACK")
        if self.fin:
            parts.append("FIN")
        if self.rst:
            parts.append("RST")
        return ",".join(parts) if parts else "-"


class Packet(BaseModel):
    """A single simulated TCP segment traveling between client and server."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)

    # Sequencing
    seq_no: int
    ack_no: Optional[int] = None

    # Classification
    flags: PacketFlags = Field(default_factory=PacketFlags)
    packet_type: PacketType

    # Addressing (simulated -- not real sockets)
    source: Role
    destination: Role
    src_port: int
    dst_port: int

    # Payload
    payload_size: int = 0
    payload_preview: Optional[str] = None
    """Truncated human-readable preview of payload, for the inspector panel."""

    # Flow control
    window_size: int

    # Integrity (see module docstring: always True, documented approximation)
    checksum_valid: bool = True

    # Timing (all virtual simulation milliseconds, not wall clock)
    sent_at_ms: float
    delivered_at_ms: Optional[float] = None
    rtt_ms: Optional[float] = None

    # Lifecycle
    status: PacketStatus = PacketStatus.IN_FLIGHT
    is_retransmission: bool = False
    original_packet_id: Optional[uuid.UUID] = None
    retransmit_count: int = 0

    # Sequencing bookkeeping for reordering visualization
    transmission_order: int
    """Monotonic counter assigned at send time; lets the UI show reordering
    (a packet delivered out of transmission_order) distinctly from loss."""

    model_config = {"use_enum_values": False}

    def mark_delivered(self, delivered_at_ms: float) -> None:
        self.delivered_at_ms = delivered_at_ms
        self.rtt_ms = delivered_at_ms - self.sent_at_ms
        self.status = PacketStatus.DELIVERED

    def mark_lost(self) -> None:
        self.status = PacketStatus.LOST

    def mark_acked(self) -> None:
        self.status = PacketStatus.ACKED


def classify_packet_type(flags: PacketFlags, payload_size: int, is_dup_ack: bool = False,
                          is_retransmission: bool = False) -> PacketType:
    """Single source of truth mapping flags/context -> PacketType.

    Centralizing this avoids the FSM and scheduler disagreeing about how a
    packet should be labeled/colored in the UI.
    """
    if is_retransmission:
        return PacketType.RETRANSMISSION
    if flags.rst:
        return PacketType.RST
    if flags.syn and flags.ack:
        return PacketType.SYN_ACK
    if flags.syn:
        return PacketType.SYN
    if flags.fin and flags.ack:
        return PacketType.FIN_ACK
    if flags.fin:
        return PacketType.FIN
    if is_dup_ack:
        return PacketType.DUP_ACK
    if payload_size > 0:
        return PacketType.DATA
    return PacketType.ACK
