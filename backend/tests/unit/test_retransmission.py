from app.models.connection import TCPConfig
from app.models.packet import Packet, PacketFlags, Role, classify_packet_type
from app.simulation.clock import SimulationClock
from app.simulation.congestion_controller import CongestionController
from app.simulation.event_bus import EventBus
from app.simulation.retransmission import RetransmissionManager, segment_end_seq


def make_manager(**config_overrides):
    config = TCPConfig(**config_overrides)
    bus = EventBus()
    clock = SimulationClock()
    congestion = CongestionController(config, bus, clock)
    events = []
    bus.subscribe(events.append)
    mgr = RetransmissionManager(Role.CLIENT, config, congestion, bus, clock)
    return mgr, clock, congestion, events


def make_data_packet(seq_no: int, size: int = 4) -> Packet:
    flags = PacketFlags()
    return Packet(
        seq_no=seq_no, ack_no=None, flags=flags,
        packet_type=classify_packet_type(flags, size),
        source=Role.CLIENT, destination=Role.SERVER,
        src_port=1000, dst_port=80, payload_size=size,
        window_size=65535, sent_at_ms=0.0, transmission_order=seq_no,
    )


def test_segment_end_seq_accounts_for_syn_and_fin():
    syn = Packet(seq_no=100, flags=PacketFlags(syn=True), packet_type=classify_packet_type(PacketFlags(syn=True), 0),
                 source=Role.CLIENT, destination=Role.SERVER, src_port=1, dst_port=2, payload_size=0,
                 window_size=1, sent_at_ms=0, transmission_order=0)
    assert segment_end_seq(syn) == 101
    data = make_data_packet(seq_no=200, size=10)
    assert segment_end_seq(data) == 210


def test_register_and_cumulative_ack_removes_entry():
    mgr, clock, _, _ = make_manager(retransmission_timeout_ms=500)
    pkt = make_data_packet(seq_no=1000, size=4)
    mgr.register_sent(pkt)
    assert mgr.in_flight_count == 1
    acked = mgr.on_ack(1004)  # covers [1000, 1004)
    assert acked == [pkt.id]
    assert mgr.in_flight_count == 0


def test_duplicate_ack_below_threshold_does_not_trigger_retransmit():
    mgr, clock, _, events = make_manager(dup_ack_threshold=3, retransmission_timeout_ms=500)
    pkt = make_data_packet(seq_no=1000, size=4)
    mgr.register_sent(pkt)
    mgr.on_ack(1000)  # first ack establishes baseline (not "new progress" beyond initial None -> is new progress actually)
    mgr.on_ack(1000)  # duplicate #1
    mgr.on_ack(1000)  # duplicate #2
    assert mgr.should_fast_retransmit_packet is None


def test_third_duplicate_ack_triggers_fast_retransmit():
    mgr, clock, congestion, events = make_manager(dup_ack_threshold=3, retransmission_timeout_ms=500)
    pkt = make_data_packet(seq_no=1000, size=4)
    mgr.register_sent(pkt)
    second_pkt = make_data_packet(seq_no=1004, size=4)
    mgr.register_sent(second_pkt)

    mgr.on_ack(1000)  # baseline
    mgr.on_ack(1000)  # dup 1
    mgr.on_ack(1000)  # dup 2
    mgr.on_ack(1000)  # dup 3 -> fast retransmit
    assert mgr.should_fast_retransmit_packet is not None
    assert mgr.should_fast_retransmit_packet.seq_no == 1000
    assert congestion.state.phase.value == "FAST_RECOVERY"


def test_timeout_fires_after_rto_elapses():
    mgr, clock, congestion, _ = make_manager(retransmission_timeout_ms=100)
    pkt = make_data_packet(seq_no=2000, size=4)
    mgr.register_sent(pkt)
    assert mgr.check_timeouts(50.0) == []  # not due yet
    results = mgr.check_timeouts(150.0)
    assert len(results) == 1
    assert results[0].entry_packet.seq_no == 2000
    assert results[0].retry_count == 1
    assert congestion.state.phase.value == "SLOW_START"  # timeout resets phase


def test_timeout_gives_up_after_max_retries():
    mgr, clock, _, events = make_manager(retransmission_timeout_ms=10, max_retries=2)
    pkt = make_data_packet(seq_no=3000, size=4)
    mgr.register_sent(pkt)

    now = 15.0
    r1 = mgr.check_timeouts(now)
    assert r1[0].exceeded_max_retries is False
    assert mgr.in_flight_count == 1

    now += 15.0
    r2 = mgr.check_timeouts(now)
    assert r2[0].exceeded_max_retries is False
    assert mgr.in_flight_count == 1

    now += 15.0
    r3 = mgr.check_timeouts(now)
    assert r3[0].exceeded_max_retries is True
    assert mgr.in_flight_count == 0  # given up, removed from tracking


def test_reset_clears_all_state():
    mgr, clock, _, _ = make_manager()
    pkt = make_data_packet(seq_no=1, size=4)
    mgr.register_sent(pkt)
    mgr.on_ack(1)
    mgr.on_ack(1)
    mgr.reset()
    assert mgr.in_flight_count == 0
    assert mgr.oldest_unacked() is None
