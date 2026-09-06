import random

from app.models.network_config import ChaosConditions, NetworkConditions
from app.models.packet import Packet, PacketFlags, Role, classify_packet_type
from app.simulation.network_simulator import NetworkSimulator


def make_packet(payload_size: int = 100) -> Packet:
    flags = PacketFlags()
    return Packet(
        seq_no=1, flags=flags, packet_type=classify_packet_type(flags, payload_size),
        source=Role.CLIENT, destination=Role.SERVER, src_port=1, dst_port=2,
        payload_size=payload_size, window_size=65535, sent_at_ms=0.0, transmission_order=0,
    )


def test_zero_loss_never_drops():
    conditions = NetworkConditions(packet_loss_percent=0.0, latency_ms=10, jitter_ms=0)
    sim = NetworkSimulator(conditions, ChaosConditions(), random.Random(1))
    for _ in range(200):
        decision = sim.transmit(make_packet(), now_ms=0.0)
        assert decision.dropped is False


def test_hundred_percent_loss_always_drops():
    conditions = NetworkConditions(packet_loss_percent=100.0)
    sim = NetworkSimulator(conditions, ChaosConditions(), random.Random(1))
    decision = sim.transmit(make_packet(), now_ms=0.0)
    assert decision.dropped is True
    assert decision.reason == "random_loss"


def test_delivery_time_is_after_send_time_and_includes_latency():
    conditions = NetworkConditions(packet_loss_percent=0.0, latency_ms=50.0, jitter_ms=0.0,
                                    bandwidth_kbps=100_000.0)
    sim = NetworkSimulator(conditions, ChaosConditions(), random.Random(1))
    decision = sim.transmit(make_packet(payload_size=10), now_ms=100.0)
    assert decision.dropped is False
    assert decision.delivery_time_ms > 100.0
    assert decision.delivery_time_ms >= 100.0 + 50.0


def test_seeded_rng_is_deterministic():
    conditions = NetworkConditions(packet_loss_percent=50.0, latency_ms=10, jitter_ms=5)
    sim_a = NetworkSimulator(conditions, ChaosConditions(), random.Random(7))
    sim_b = NetworkSimulator(conditions, ChaosConditions(), random.Random(7))
    results_a = [sim_a.transmit(make_packet(), now_ms=0.0).dropped for _ in range(50)]
    results_b = [sim_b.transmit(make_packet(), now_ms=0.0).dropped for _ in range(50)]
    assert results_a == results_b


def test_buffer_overflow_drops_when_chaos_enabled():
    conditions = NetworkConditions(packet_loss_percent=0.0, buffer_size_kb=1.0)  # 1024 bytes
    chaos = ChaosConditions(buffer_overflow_enabled=True)
    sim = NetworkSimulator(conditions, chaos, random.Random(1))
    # First packet fits and occupies the buffer (never released in this test).
    first = sim.transmit(make_packet(payload_size=800), now_ms=0.0)
    assert first.dropped is False
    # Second packet would exceed the 1024-byte buffer.
    second = sim.transmit(make_packet(payload_size=800), now_ms=0.0)
    assert second.dropped is True
    assert second.reason == "buffer_overflow"


def test_release_buffer_frees_capacity():
    conditions = NetworkConditions(packet_loss_percent=0.0, buffer_size_kb=1.0)
    chaos = ChaosConditions(buffer_overflow_enabled=True)
    sim = NetworkSimulator(conditions, chaos, random.Random(1))
    pkt = make_packet(payload_size=800)
    sim.transmit(pkt, now_ms=0.0)
    sim.release_buffer(800)
    second = sim.transmit(make_packet(payload_size=800), now_ms=0.0)
    assert second.dropped is False


def test_burst_loss_drops_consecutive_packets():
    conditions = NetworkConditions(packet_loss_percent=0.0)
    chaos = ChaosConditions(random_burst_loss_enabled=True, burst_loss_trigger_percent=100.0, burst_loss_size=3)
    sim = NetworkSimulator(conditions, chaos, random.Random(1))
    results = [sim.transmit(make_packet(), now_ms=0.0) for _ in range(3)]
    assert all(r.dropped and r.reason == "burst_loss" for r in results)
