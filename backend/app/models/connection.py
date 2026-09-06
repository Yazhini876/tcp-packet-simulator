"""Per-endpoint TCP connection state and static TCP configuration."""
from __future__ import annotations

import uuid
from typing import Dict, Optional

from pydantic import BaseModel, Field

from app.models.packet import Packet, Role
from app.models.tcp_state import TCPState


class TCPConfig(BaseModel):
    """User-tunable TCP parameters (left panel controls)."""

    mss_bytes: int = Field(default=536, ge=1, le=65495,
                            description="Maximum Segment Size in bytes")
    initial_cwnd_segments: int = Field(default=1, ge=1, le=1000)
    retransmission_timeout_ms: float = Field(default=1000.0, ge=10.0, le=100_000.0)
    max_retries: int = Field(default=5, ge=1, le=15)
    dup_ack_threshold: int = Field(default=3, ge=1, le=10)
    ssthresh_initial_segments: int = Field(default=64, ge=2, le=1000)
    time_wait_ms: float = Field(
        default=2000.0,
        description=(
            "Simulation approximation: real TCP uses 2xMSL (often minutes). "
            "We use a short fixed virtual delay so users are not stuck waiting."
        ),
    )


class RetransmitQueueEntry(BaseModel):
    """Tracks a segment that has been sent but not yet ACKed."""

    packet: Packet
    rto_deadline_ms: float
    retry_count: int = 0


class ConnectionEndpoint(BaseModel):
    """The client or server side of a simulated TCP connection.

    Mirrors the classic TCP control-block variables (SND.NXT, SND.UNA,
    RCV.NXT) using explicit names for clarity in an educational context.
    """

    role: Role
    state: TCPState = TCPState.CLOSED
    ip: str
    port: int

    initial_seq_no: int
    send_next_seq: int = 0
    """SND.NXT -- sequence number of the next byte to send."""
    send_unacked_seq: int = 0
    """SND.UNA -- oldest unacknowledged sequence number."""
    recv_next_seq: int = 0
    """RCV.NXT -- next expected sequence number from the peer."""

    peer_initial_seq_no: Optional[int] = None

    window_size: int = 65535

    # Retransmission bookkeeping: packet_id -> queue entry
    retransmit_queue: Dict[uuid.UUID, RetransmitQueueEntry] = Field(default_factory=dict)

    # Duplicate ACK tracking, keyed by the ack_no being duplicated
    last_ack_no_seen: Optional[int] = None
    dup_ack_count: int = 0

    def reset(self) -> None:
        self.state = TCPState.CLOSED
        self.send_next_seq = self.initial_seq_no
        self.send_unacked_seq = self.initial_seq_no
        self.recv_next_seq = 0
        self.peer_initial_seq_no = None
        self.retransmit_queue.clear()
        self.last_ack_no_seen = None
        self.dup_ack_count = 0
