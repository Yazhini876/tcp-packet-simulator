from app.models.connection import TCPConfig
from tests.conftest import make_session


def test_lossy_data_transfer_still_completes_via_timeout_retransmit():
    """With no reordering/duplicate-ack machinery in play (loss spread out
    so dup-ack fast retransmit may or may not trigger), the message must
    still arrive completely -- retransmission via RTO is the safety net."""
    config = TCPConfig(mss_bytes=4, retransmission_timeout_ms=150.0, max_retries=10, time_wait_ms=50.0)
    session = make_session(seed=123, loss_percent=25.0, latency_ms=20.0, tcp_config=config)
    session.start()
    session.run_until_idle(max_events=500)

    session.send_message("HELLO TCP NETWORK LAB")
    session.run_until_idle(max_events=2000)

    message_len = len("HELLO TCP NETWORK LAB".encode("utf-8"))
    expected_recv_seq = session.client.initial_seq_no + 1 + message_len
    assert session.server.recv_next_seq == expected_recv_seq


def test_retransmission_count_is_positive_under_loss():
    config = TCPConfig(mss_bytes=4, retransmission_timeout_ms=150.0, max_retries=10, time_wait_ms=50.0)
    session = make_session(seed=7, loss_percent=30.0, latency_ms=20.0, tcp_config=config)

    retransmit_count = 0

    def on_event(event):
        nonlocal retransmit_count
        if event.type == "packet_retransmitted":
            retransmit_count += 1

    session.event_bus.subscribe(on_event)
    session.start()
    session.run_until_idle(max_events=500)
    session.send_message("RETRY ME PLEASE THANKS")
    session.run_until_idle(max_events=3000)

    assert retransmit_count > 0


def test_retransmitted_packet_is_flagged_and_linked_to_original():
    config = TCPConfig(mss_bytes=4, retransmission_timeout_ms=100.0, max_retries=10, time_wait_ms=50.0)
    session = make_session(seed=99, loss_percent=50.0, latency_ms=10.0, tcp_config=config)

    retransmits = []
    session.event_bus.subscribe(
        lambda e: retransmits.append(e) if e.type == "packet_retransmitted" else None
    )
    session.start()
    session.run_until_idle(max_events=500)
    session.send_message("HI")
    session.run_until_idle(max_events=2000)

    assert len(retransmits) > 0
    for r in retransmits:
        assert r.packet.is_retransmission is True
        assert r.packet.original_packet_id == r.original_packet_id


def test_fast_retransmit_triggers_when_first_segment_is_lost():
    """Deterministic reproduction of fast retransmit: force exactly the
    first DATA segment to be lost (via a targeted monkeypatch of the
    network simulator's `transmit`), let the following segments arrive
    normally to generate three duplicate ACKs, and confirm fast retransmit
    fires (RTO is set very high so only the dup-ACK path can explain it).
    """
    from app.simulation.network_simulator import DeliveryDecision

    config = TCPConfig(
        mss_bytes=2, initial_cwnd_segments=8, ssthresh_initial_segments=100,
        retransmission_timeout_ms=100_000.0,  # effectively disabled for this test
        dup_ack_threshold=3, max_retries=10, time_wait_ms=50.0,
    )
    session = make_session(seed=1, loss_percent=0.0, latency_ms=5.0, tcp_config=config)
    session.start()
    session.run_until_idle(max_events=200)

    original_transmit = session.network_simulator.transmit
    state = {"dropped_first_segment": False}

    def selective_drop(packet, now_ms):
        if not state["dropped_first_segment"] and packet.payload_size > 0:
            state["dropped_first_segment"] = True
            return DeliveryDecision(dropped=True, reason="random_loss")
        return original_transmit(packet, now_ms)

    session.network_simulator.transmit = selective_drop  # type: ignore[method-assign]

    fast_retransmits = []
    session.event_bus.subscribe(
        lambda e: fast_retransmits.append(e) if e.type == "fast_retransmit_triggered" else None
    )

    session.send_message("ABCDEFGHIJKL")  # 6 segments of 2 bytes at mss=2
    session.run_until_idle(max_events=500)

    assert len(fast_retransmits) >= 1
