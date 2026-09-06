from app.models.events import (
    DupAckDetectedEvent,
    PacketDeliveredEvent,
    PacketLostEvent,
    PacketRetransmittedEvent,
    PacketSentEvent,
    StateChangedEvent,
    TimeoutOccurredEvent,
)
from app.models.packet import Packet, PacketFlags, Role, classify_packet_type
from app.models.statistics import SimulationStatistics
from app.models.tcp_state import TCPState
from app.services.statistics_engine import reduce_event


def make_packet(seq_no=1, payload_size=10, rtt_ms=None, is_retransmission=False):
    flags = PacketFlags()
    pkt = Packet(
        seq_no=seq_no, flags=flags, packet_type=classify_packet_type(flags, payload_size),
        source=Role.CLIENT, destination=Role.SERVER, src_port=1, dst_port=2,
        payload_size=payload_size, window_size=65535, sent_at_ms=0.0, transmission_order=0,
        is_retransmission=is_retransmission,
    )
    if rtt_ms is not None:
        pkt.rtt_ms = rtt_ms
    return pkt


def test_packet_sent_increments_counter():
    stats = SimulationStatistics()
    reduce_event(stats, PacketSentEvent(session_time_ms=1.0, packet=make_packet()))
    assert stats.packets_sent == 1


def test_packet_delivered_tracks_bytes_and_rtt():
    stats = SimulationStatistics()
    pkt = make_packet(payload_size=100, rtt_ms=42.0)
    reduce_event(stats, PacketDeliveredEvent(session_time_ms=42.0, packet=pkt))
    assert stats.packets_delivered == 1
    assert stats.bytes_delivered_total == 100
    assert stats.bytes_delivered_unique == 100
    assert stats.rtt_avg_ms == 42.0
    assert stats.rtt_min_ms == 42.0
    assert stats.rtt_max_ms == 42.0


def test_retransmitted_packet_counts_toward_total_but_not_unique_bytes():
    stats = SimulationStatistics()
    original = make_packet(payload_size=50)
    retransmit = make_packet(payload_size=50, rtt_ms=10.0, is_retransmission=True)
    reduce_event(stats, PacketDeliveredEvent(session_time_ms=10.0, packet=retransmit))
    assert stats.bytes_delivered_total == 50
    assert stats.bytes_delivered_unique == 0


def test_lost_retransmit_dupack_timeout_counters():
    stats = SimulationStatistics()
    reduce_event(stats, PacketLostEvent(session_time_ms=1.0, packet=make_packet(), reason="random_loss"))
    reduce_event(stats, PacketRetransmittedEvent(session_time_ms=2.0, packet=make_packet(),
                                                   original_packet_id=make_packet().id, cause="timeout"))
    reduce_event(stats, DupAckDetectedEvent(session_time_ms=3.0, ack_no=100, dup_count=1, role=Role.CLIENT))
    reduce_event(stats, TimeoutOccurredEvent(session_time_ms=4.0, seq_no=1, retry_count=1))
    assert stats.packets_lost == 1
    assert stats.retransmissions == 1
    assert stats.duplicate_acks == 1
    assert stats.timeouts == 1


def test_state_changed_updates_correct_role():
    stats = SimulationStatistics()
    reduce_event(stats, StateChangedEvent(session_time_ms=1.0, role=Role.CLIENT,
                                            previous_state=TCPState.CLOSED,
                                            new_state=TCPState.SYN_SENT, trigger="APP_OPEN"))
    reduce_event(stats, StateChangedEvent(session_time_ms=1.0, role=Role.SERVER,
                                            previous_state=TCPState.CLOSED,
                                            new_state=TCPState.LISTEN, trigger="APP_PASSIVE_OPEN"))
    assert stats.current_state_client == TCPState.SYN_SENT
    assert stats.current_state_server == TCPState.LISTEN


def test_loss_rate_recomputed_after_each_event():
    stats = SimulationStatistics()
    for _ in range(3):
        reduce_event(stats, PacketSentEvent(session_time_ms=1.0, packet=make_packet()))
    reduce_event(stats, PacketLostEvent(session_time_ms=1.0, packet=make_packet(), reason="random_loss"))
    assert round(stats.packet_loss_rate_percent, 2) == round(100 / 3, 2)


def test_elapsed_ms_tracks_latest_event_time():
    stats = SimulationStatistics()
    reduce_event(stats, PacketSentEvent(session_time_ms=5.0, packet=make_packet()))
    reduce_event(stats, PacketSentEvent(session_time_ms=3.0, packet=make_packet()))
    reduce_event(stats, PacketSentEvent(session_time_ms=9.0, packet=make_packet()))
    assert stats.elapsed_ms == 9.0
