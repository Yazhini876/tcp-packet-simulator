from app.models.congestion import CongestionPhase
from app.models.connection import TCPConfig
from app.simulation.clock import SimulationClock
from app.simulation.congestion_controller import CongestionController
from app.simulation.event_bus import EventBus


def make_controller(**config_overrides):
    config = TCPConfig(**config_overrides)
    bus = EventBus()
    clock = SimulationClock()
    events = []
    bus.subscribe(events.append)
    return CongestionController(config, bus, clock), events


def test_slow_start_grows_exponentially_per_ack():
    controller, _ = make_controller(initial_cwnd_segments=1, ssthresh_initial_segments=100)
    assert controller.cwnd_segments == 1
    controller.on_new_ack()
    assert controller.cwnd_segments == 2
    controller.on_new_ack()
    assert controller.cwnd_segments == 3
    assert controller.state.phase == CongestionPhase.SLOW_START


def test_transitions_to_congestion_avoidance_at_ssthresh():
    controller, _ = make_controller(initial_cwnd_segments=1, ssthresh_initial_segments=4)
    for _ in range(3):
        controller.on_new_ack()
    assert controller.cwnd_segments == 4
    assert controller.state.phase == CongestionPhase.CONGESTION_AVOIDANCE


def test_congestion_avoidance_grows_additively():
    controller, _ = make_controller(initial_cwnd_segments=4, ssthresh_initial_segments=4)
    # Already at/above ssthresh -> first ack should be evaluated in slow
    # start phase per implementation (transitions on crossing), so force
    # phase via one ack first.
    controller.on_new_ack()  # cwnd=5, still slow start check crosses since 4>=4 already applied on init? verify below
    assert controller.state.phase == CongestionPhase.CONGESTION_AVOIDANCE
    cwnd_before = controller.cwnd_segments
    controller.on_new_ack()
    # Additive increase should be much smaller than the doubling seen in slow start.
    assert controller.cwnd_segments > cwnd_before
    assert controller.cwnd_segments - cwnd_before <= 1.0


def test_fast_retransmit_halves_and_sets_recovery():
    controller, _ = make_controller(initial_cwnd_segments=16, ssthresh_initial_segments=100)
    controller.on_fast_retransmit()
    assert controller.state.phase == CongestionPhase.FAST_RECOVERY
    assert controller.state.ssthresh_segments == 8.0
    assert controller.cwnd_segments == 11.0  # ssthresh + 3


def test_fast_recovery_exit_deflates_to_ssthresh():
    controller, _ = make_controller(initial_cwnd_segments=16, ssthresh_initial_segments=100)
    controller.on_fast_retransmit()
    ssthresh = controller.state.ssthresh_segments
    controller.on_new_ack(is_recovery_ack=True)
    assert controller.cwnd_segments == ssthresh
    assert controller.state.phase == CongestionPhase.CONGESTION_AVOIDANCE


def test_duplicate_ack_inflates_window_during_recovery():
    controller, _ = make_controller(initial_cwnd_segments=16, ssthresh_initial_segments=100)
    controller.on_fast_retransmit()
    cwnd_before = controller.cwnd_segments
    controller.on_duplicate_ack_during_recovery()
    assert controller.cwnd_segments == cwnd_before + 1


def test_timeout_resets_to_slow_start():
    controller, _ = make_controller(initial_cwnd_segments=20, ssthresh_initial_segments=100)
    controller.on_timeout()
    assert controller.state.phase == CongestionPhase.SLOW_START
    assert controller.cwnd_segments == 1.0
    assert controller.state.ssthresh_segments == 10.0


def test_ssthresh_never_drops_below_minimum():
    controller, _ = make_controller(initial_cwnd_segments=2, ssthresh_initial_segments=100)
    controller.on_timeout()
    assert controller.state.ssthresh_segments >= 2.0


def test_history_records_every_event():
    controller, _ = make_controller(initial_cwnd_segments=1, ssthresh_initial_segments=100)
    controller.on_new_ack()
    controller.on_fast_retransmit()
    controller.on_timeout()
    assert len(controller.state.history) == 3
    assert [s.event.value for s in controller.state.history] == ["GROWTH", "DUP_ACK_FAST_RETRANSMIT", "TIMEOUT"]


def test_cwnd_updated_event_published_on_each_change():
    controller, events = make_controller(initial_cwnd_segments=1, ssthresh_initial_segments=100)
    controller.on_new_ack()
    assert len(events) == 1
    assert events[0].type == "cwnd_updated"
    assert events[0].cwnd_segments == 2.0
