from app.models.tcp_state import TCPState
from tests.conftest import make_session


def test_handshake_completes_with_zero_loss():
    session = make_session(loss_percent=0.0, latency_ms=20.0)
    session.start()
    session.run_until_idle(max_events=20)

    assert session.client_fsm.state == TCPState.ESTABLISHED
    assert session.server_fsm.state == TCPState.ESTABLISHED


def test_handshake_sequence_numbers_are_consistent():
    session = make_session(loss_percent=0.0, latency_ms=20.0)
    session.start()
    session.run_until_idle(max_events=20)

    # Client's initial seq + 1 (consumed by SYN) should equal server's
    # recorded recv_next_seq after the handshake.
    assert session.server.recv_next_seq == session.client.initial_seq_no + 1
    assert session.client.recv_next_seq == session.server.initial_seq_no + 1


def test_handshake_emits_three_packet_sent_events():
    session = make_session(loss_percent=0.0, latency_ms=20.0)
    sent_types = []
    session.event_bus.subscribe(
        lambda e: sent_types.append(e.packet.packet_type) if e.type == "packet_sent" else None
    )
    session.start()
    session.run_until_idle(max_events=20)

    assert sent_types == ["SYN", "SYN-ACK", "ACK"]


def test_handshake_with_high_latency_still_completes():
    session = make_session(loss_percent=0.0, latency_ms=500.0, jitter_ms=50.0)
    session.start()
    processed = session.run_until_idle(max_events=50)
    assert processed > 0
    assert session.client_fsm.state == TCPState.ESTABLISHED
    assert session.server_fsm.state == TCPState.ESTABLISHED
    # High latency should be reflected in when ESTABLISHED was reached.
    assert session.clock.now_ms >= 500.0
