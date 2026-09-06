"""TCP connection state enum and the transition-trigger vocabulary used by
`simulation/state_machine.py`.

Keeping the enum + trigger definitions here (separate from the FSM logic)
lets both the backend transition table and the frontend TS mirror
(`types/tcpState.ts`) reference a single, stable vocabulary.
"""
from __future__ import annotations

from enum import Enum


class TCPState(str, Enum):
    CLOSED = "CLOSED"
    LISTEN = "LISTEN"
    SYN_SENT = "SYN_SENT"
    SYN_RECEIVED = "SYN_RECEIVED"
    ESTABLISHED = "ESTABLISHED"
    FIN_WAIT_1 = "FIN_WAIT_1"
    FIN_WAIT_2 = "FIN_WAIT_2"
    CLOSING = "CLOSING"
    """Simultaneous-close edge case: both sides send FIN before receiving the
    peer's FIN. Supported for correctness but not a primary teaching path."""
    CLOSE_WAIT = "CLOSE_WAIT"
    LAST_ACK = "LAST_ACK"
    TIME_WAIT = "TIME_WAIT"


class Trigger(str, Enum):
    """Events that can cause a TCP state transition.

    Named from the perspective of "what just happened to this endpoint",
    matching standard TCP state-diagram terminology.
    """

    APP_OPEN = "APP_OPEN"                    # active open: app calls connect()
    APP_PASSIVE_OPEN = "APP_PASSIVE_OPEN"    # passive open: server starts listening
    RECV_SYN = "RECV_SYN"
    RECV_SYN_ACK = "RECV_SYN_ACK"
    RECV_ACK = "RECV_ACK"
    APP_CLOSE = "APP_CLOSE"                  # app calls close()
    RECV_FIN = "RECV_FIN"
    RECV_FIN_ACK = "RECV_FIN_ACK"
    TIME_WAIT_EXPIRED = "TIME_WAIT_EXPIRED"


# States in which the connection is usable for application data transfer.
DATA_TRANSFER_STATES = frozenset({TCPState.ESTABLISHED})

# Terminal state.
CLOSED_STATES = frozenset({TCPState.CLOSED})
