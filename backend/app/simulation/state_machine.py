"""TCP connection state machine.

Each endpoint (client, server) owns one `TCPStateMachine` instance. The
transition table is declarative: `(current_state, trigger) -> next_state`.
This keeps the FSM logic testable in complete isolation from packets,
timers, or the network simulator -- a test can drive it with nothing but a
sequence of `Trigger`s and assert the resulting state sequence.

Side effects (building/sending packets) are NOT performed here. The FSM's
only job is legal-transition bookkeeping and emitting `StateChangedEvent`s.
The `SimulationSession` (built in a later step of Phase 2) is responsible
for calling `apply()` and then reacting to the resulting state with the
appropriate packet construction.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

from app.models.events import StateChangedEvent
from app.models.packet import Role
from app.models.tcp_state import TCPState, Trigger
from app.simulation.clock import SimulationClock
from app.simulation.event_bus import EventBus


class TCPProtocolError(Exception):
    """Raised when a trigger is applied that has no legal transition from
    the current state. Deliberately loud rather than silently ignored --
    an invalid transition is itself an educational signal worth surfacing
    in the event log."""

    def __init__(self, role: Role, state: TCPState, trigger: Trigger) -> None:
        self.role = role
        self.state = state
        self.trigger = trigger
        super().__init__(
            f"Illegal transition for {role.value}: no rule for "
            f"trigger={trigger.value} in state={state.value}"
        )


# (current_state, trigger) -> next_state
TransitionTable = Dict[Tuple[TCPState, Trigger], TCPState]

_TRANSITIONS: TransitionTable = {
    # --- Connection establishment ---
    (TCPState.CLOSED, Trigger.APP_PASSIVE_OPEN): TCPState.LISTEN,
    (TCPState.CLOSED, Trigger.APP_OPEN): TCPState.SYN_SENT,
    (TCPState.LISTEN, Trigger.RECV_SYN): TCPState.SYN_RECEIVED,
    (TCPState.SYN_SENT, Trigger.RECV_SYN_ACK): TCPState.ESTABLISHED,
    (TCPState.SYN_RECEIVED, Trigger.RECV_ACK): TCPState.ESTABLISHED,

    # --- Active close (the side that initiates termination) ---
    (TCPState.ESTABLISHED, Trigger.APP_CLOSE): TCPState.FIN_WAIT_1,
    (TCPState.FIN_WAIT_1, Trigger.RECV_ACK): TCPState.FIN_WAIT_2,
    (TCPState.FIN_WAIT_1, Trigger.RECV_FIN): TCPState.CLOSING,
    (TCPState.FIN_WAIT_2, Trigger.RECV_FIN): TCPState.TIME_WAIT,
    (TCPState.CLOSING, Trigger.RECV_ACK): TCPState.TIME_WAIT,
    (TCPState.TIME_WAIT, Trigger.TIME_WAIT_EXPIRED): TCPState.CLOSED,

    # --- Passive close (the side that receives FIN first) ---
    (TCPState.ESTABLISHED, Trigger.RECV_FIN): TCPState.CLOSE_WAIT,
    (TCPState.CLOSE_WAIT, Trigger.APP_CLOSE): TCPState.LAST_ACK,
    (TCPState.LAST_ACK, Trigger.RECV_ACK): TCPState.CLOSED,
}


class TCPStateMachine:
    def __init__(self, role: Role, event_bus: EventBus, clock: SimulationClock,
                 initial_state: TCPState = TCPState.CLOSED) -> None:
        self.role = role
        self._event_bus = event_bus
        self._clock = clock
        self.state = initial_state

    def can_apply(self, trigger: Trigger) -> bool:
        return (self.state, trigger) in _TRANSITIONS

    def apply(self, trigger: Trigger) -> TCPState:
        """Attempt the transition for `trigger` from the current state.

        Raises `TCPProtocolError` if illegal. On success, updates
        `self.state` and publishes a `StateChangedEvent`.
        """
        key = (self.state, trigger)
        next_state = _TRANSITIONS.get(key)
        if next_state is None:
            raise TCPProtocolError(self.role, self.state, trigger)

        previous_state = self.state
        self.state = next_state
        self._event_bus.publish(
            StateChangedEvent(
                session_time_ms=self._clock.now_ms,
                role=self.role,
                previous_state=previous_state,
                new_state=next_state,
                trigger=trigger.value,
            )
        )
        return next_state

    def reset(self, initial_state: TCPState = TCPState.CLOSED) -> None:
        self.state = initial_state
