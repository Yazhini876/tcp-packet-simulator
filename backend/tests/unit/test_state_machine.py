import pytest

from app.models.packet import Role
from app.models.tcp_state import TCPState, Trigger
from app.simulation.clock import SimulationClock
from app.simulation.event_bus import EventBus
from app.simulation.state_machine import TCPProtocolError, TCPStateMachine


def make_fsm(role=Role.CLIENT):
    bus = EventBus()
    clock = SimulationClock()
    events = []
    bus.subscribe(events.append)
    return TCPStateMachine(role, bus, clock), events


def test_client_handshake_sequence():
    fsm, events = make_fsm(Role.CLIENT)
    assert fsm.state == TCPState.CLOSED
    assert fsm.apply(Trigger.APP_OPEN) == TCPState.SYN_SENT
    assert fsm.apply(Trigger.RECV_SYN_ACK) == TCPState.ESTABLISHED
    assert len(events) == 2
    assert events[0].new_state == TCPState.SYN_SENT
    assert events[1].new_state == TCPState.ESTABLISHED


def test_server_handshake_sequence():
    fsm, _ = make_fsm(Role.SERVER)
    assert fsm.apply(Trigger.APP_PASSIVE_OPEN) == TCPState.LISTEN
    assert fsm.apply(Trigger.RECV_SYN) == TCPState.SYN_RECEIVED
    assert fsm.apply(Trigger.RECV_ACK) == TCPState.ESTABLISHED


def test_active_close_sequence_client():
    fsm, _ = make_fsm(Role.CLIENT)
    fsm.apply(Trigger.APP_OPEN)
    fsm.apply(Trigger.RECV_SYN_ACK)
    assert fsm.state == TCPState.ESTABLISHED

    assert fsm.apply(Trigger.APP_CLOSE) == TCPState.FIN_WAIT_1
    assert fsm.apply(Trigger.RECV_ACK) == TCPState.FIN_WAIT_2
    assert fsm.apply(Trigger.RECV_FIN) == TCPState.TIME_WAIT
    assert fsm.apply(Trigger.TIME_WAIT_EXPIRED) == TCPState.CLOSED


def test_passive_close_sequence_server():
    fsm, _ = make_fsm(Role.SERVER)
    fsm.apply(Trigger.APP_PASSIVE_OPEN)
    fsm.apply(Trigger.RECV_SYN)
    fsm.apply(Trigger.RECV_ACK)
    assert fsm.state == TCPState.ESTABLISHED

    assert fsm.apply(Trigger.RECV_FIN) == TCPState.CLOSE_WAIT
    assert fsm.apply(Trigger.APP_CLOSE) == TCPState.LAST_ACK
    assert fsm.apply(Trigger.RECV_ACK) == TCPState.CLOSED


def test_simultaneous_close_edge_case():
    fsm, _ = make_fsm(Role.CLIENT)
    fsm.apply(Trigger.APP_OPEN)
    fsm.apply(Trigger.RECV_SYN_ACK)
    fsm.apply(Trigger.APP_CLOSE)  # -> FIN_WAIT_1
    assert fsm.apply(Trigger.RECV_FIN) == TCPState.CLOSING
    assert fsm.apply(Trigger.RECV_ACK) == TCPState.TIME_WAIT


def test_illegal_transition_raises():
    fsm, _ = make_fsm(Role.CLIENT)
    with pytest.raises(TCPProtocolError):
        fsm.apply(Trigger.RECV_ACK)  # can't ACK before even opening
    # State must remain unchanged after a failed transition.
    assert fsm.state == TCPState.CLOSED


def test_can_apply_reports_legality_without_mutating():
    fsm, _ = make_fsm(Role.CLIENT)
    assert fsm.can_apply(Trigger.APP_OPEN) is True
    assert fsm.can_apply(Trigger.RECV_ACK) is False
    assert fsm.state == TCPState.CLOSED
