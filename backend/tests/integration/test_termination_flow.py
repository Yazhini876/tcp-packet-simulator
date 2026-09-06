from app.models.connection import TCPConfig
from app.models.tcp_state import TCPState
from tests.conftest import make_session


def test_full_lifecycle_ends_with_both_sides_closed():
    config = TCPConfig(retransmission_timeout_ms=200.0, time_wait_ms=30.0)
    session = make_session(loss_percent=0.0, latency_ms=10.0, tcp_config=config)
    session.start()
    session.run_until_idle()

    session.send_message("BYE")
    session.run_until_idle()

    session.close()
    session.run_until_idle(max_events=200)

    assert session.client_fsm.state == TCPState.CLOSED
    assert session.server_fsm.state == TCPState.CLOSED
    assert session.is_closed


def test_close_before_established_is_a_no_op():
    session = make_session()
    session.close()  # never started
    assert session.client_fsm.state == TCPState.CLOSED


def test_termination_emits_connection_closed_event():
    config = TCPConfig(retransmission_timeout_ms=200.0, time_wait_ms=30.0)
    session = make_session(loss_percent=0.0, latency_ms=10.0, tcp_config=config)
    closed_events = []
    session.event_bus.subscribe(
        lambda e: closed_events.append(e) if e.type == "connection_closed" else None
    )
    session.start()
    session.run_until_idle()
    session.close()
    session.run_until_idle(max_events=200)

    assert len(closed_events) >= 1


def test_client_state_sequence_through_active_close():
    config = TCPConfig(retransmission_timeout_ms=200.0, time_wait_ms=30.0)
    session = make_session(loss_percent=0.0, latency_ms=10.0, tcp_config=config)
    states = []
    session.event_bus.subscribe(
        lambda e: states.append(e.new_state) if e.type == "state_changed" and e.role.value == "client" else None
    )
    session.start()
    session.run_until_idle()
    session.close()
    session.run_until_idle(max_events=200)

    assert states == [
        TCPState.SYN_SENT,
        TCPState.ESTABLISHED,
        TCPState.FIN_WAIT_1,
        TCPState.FIN_WAIT_2,
        TCPState.TIME_WAIT,
        TCPState.CLOSED,
    ]


def test_termination_with_packet_loss_still_completes():
    config = TCPConfig(retransmission_timeout_ms=150.0, max_retries=10, time_wait_ms=30.0)
    session = make_session(seed=55, loss_percent=20.0, latency_ms=15.0, tcp_config=config)
    session.start()
    session.run_until_idle(max_events=500)
    session.close()
    session.run_until_idle(max_events=2000)

    assert session.is_closed
