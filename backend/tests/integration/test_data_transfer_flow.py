from app.models.connection import TCPConfig
from app.models.tcp_state import TCPState
from tests.conftest import make_session


def test_message_is_fully_delivered_with_zero_loss():
    config = TCPConfig(mss_bytes=4, retransmission_timeout_ms=300.0, time_wait_ms=50.0)
    session = make_session(loss_percent=0.0, latency_ms=10.0, tcp_config=config)
    session.start()
    session.run_until_idle()

    session.send_message("HELLO TCP NETWORK")
    session.run_until_idle()

    delivered_payloads = []

    def collect(event):
        if event.type == "packet_delivered" and event.packet.payload_size > 0:
            delivered_payloads.append(event.packet)

    # Re-run isn't possible after the fact (events already fired), so
    # instead verify via server's recv_next_seq advancing by the full
    # message length, which only happens if every segment arrived in order.
    message_len = len("HELLO TCP NETWORK".encode("utf-8"))
    expected_recv_seq = session.client.initial_seq_no + 1 + message_len
    assert session.server.recv_next_seq == expected_recv_seq


def test_segments_respect_configured_mss():
    config = TCPConfig(mss_bytes=5, retransmission_timeout_ms=300.0, time_wait_ms=50.0)
    session = make_session(loss_percent=0.0, latency_ms=5.0, tcp_config=config)
    sent_data_sizes = []
    session.event_bus.subscribe(
        lambda e: sent_data_sizes.append(e.packet.payload_size)
        if e.type == "packet_sent" and e.packet.packet_type.value == "DATA"
        else None
    )
    session.start()
    session.run_until_idle()
    session.send_message("HELLO TCP NETWORK")  # 17 bytes
    session.run_until_idle()

    assert sent_data_sizes == [5, 5, 5, 2]


def test_congestion_window_grows_during_slow_start():
    config = TCPConfig(mss_bytes=2, initial_cwnd_segments=1, ssthresh_initial_segments=100,
                        retransmission_timeout_ms=300.0, time_wait_ms=50.0)
    session = make_session(loss_percent=0.0, latency_ms=5.0, tcp_config=config)
    session.start()
    session.run_until_idle()
    session.send_message("AAAAAAAAAAAAAAAAAAAA")  # 20 bytes -> 10 segments of 2 bytes
    session.run_until_idle()

    assert session.client_congestion.cwnd_segments > 1.0


def test_cannot_send_before_established():
    session = make_session()
    # Not started -> still CLOSED
    session.send_message("too early")
    assert session.client.send_next_seq == 0  # nothing was transmitted
