"""Applies configured network conditions to determine a packet's fate:
delivered (and when), lost (and why), or reordered.

SIMULATION APPROXIMATIONS (documented per project rules):
  - Bandwidth is modeled purely as an added serialization delay
    (payload_bits / bandwidth_bps), not a true shared-link queuing model.
  - Buffer occupancy is tracked as a simple sum of in-flight bytes; when it
    would exceed `buffer_size_kb`, the new packet is dropped outright
    rather than queued (simplified "tail drop").
  - Reordering is modeled by adding extra delay to a packet so it arrives
    after packets sent slightly later, not through a real per-packet queue
    with independent paths.

All randomness is drawn from a `random.Random` instance owned by the
session (seeded), so simulation runs are reproducible for tests and for
Experiment Mode result stability.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

from app.models.network_config import ChaosConditions, NetworkConditions
from app.models.packet import Packet


@dataclass
class DeliveryDecision:
    dropped: bool
    reason: Optional[str] = None
    """One of 'random_loss', 'buffer_overflow', 'burst_loss' when dropped."""
    delivery_time_ms: Optional[float] = None
    reordered: bool = False


class NetworkSimulator:
    def __init__(self, conditions: NetworkConditions, chaos: ChaosConditions,
                 rng: random.Random) -> None:
        self.conditions = conditions
        self.chaos = chaos
        self._rng = rng
        self._in_flight_bytes: float = 0.0
        self._burst_remaining: int = 0

    def update_conditions(self, conditions: NetworkConditions) -> None:
        self.conditions = conditions

    def update_chaos(self, chaos: ChaosConditions) -> None:
        self.chaos = chaos

    def release_buffer(self, payload_size: int) -> None:
        """Call when a packet leaves the simulated buffer (delivered)."""
        self._in_flight_bytes = max(0.0, self._in_flight_bytes - payload_size)

    def transmit(self, packet: Packet, now_ms: float) -> DeliveryDecision:
        # 1) Burst loss (chaos mode): once triggered, drop N consecutive
        #    packets regardless of the normal loss roll.
        if self.chaos.random_burst_loss_enabled:
            if self._burst_remaining > 0:
                self._burst_remaining -= 1
                return DeliveryDecision(dropped=True, reason="burst_loss")
            if self._rng.random() * 100 < self.chaos.burst_loss_trigger_percent:
                self._burst_remaining = max(self.chaos.burst_loss_size - 1, 0)
                return DeliveryDecision(dropped=True, reason="burst_loss")

        # 2) Buffer overflow (chaos mode): reject if the buffer is full.
        buffer_capacity_bytes = self.conditions.buffer_size_kb * 1024
        if self.chaos.buffer_overflow_enabled:
            if self._in_flight_bytes + packet.payload_size > buffer_capacity_bytes:
                return DeliveryDecision(dropped=True, reason="buffer_overflow")

        # 3) Baseline random loss.
        if self._rng.random() * 100 < self.conditions.packet_loss_percent:
            return DeliveryDecision(dropped=True, reason="random_loss")

        # Packet survives -- occupy buffer space until delivered.
        self._in_flight_bytes += packet.payload_size

        delay_ms = self._compute_delay_ms(packet)
        reordered = self._roll_reorder()
        if reordered:
            # Push it noticeably later than a "normal" packet so it lands
            # behind subsequently-sent packets -- visualized in the UI as
            # an out-of-order arrival rather than a drop.
            multiplier = self.chaos.reorder_multiplier if self.chaos.reordering_enabled else 2.0
            delay_ms *= multiplier

        return DeliveryDecision(
            dropped=False,
            delivery_time_ms=now_ms + delay_ms,
            reordered=reordered,
        )

    def _compute_delay_ms(self, packet: Packet) -> float:
        base_latency = self.conditions.latency_ms
        if self.chaos.high_latency_enabled:
            base_latency *= self.chaos.high_latency_multiplier

        jitter = self.conditions.jitter_ms
        jitter_sample = self._rng.uniform(-jitter, jitter) if jitter > 0 else 0.0

        bandwidth_kbps = self.conditions.bandwidth_kbps
        if self.chaos.bandwidth_cap_enabled:
            bandwidth_kbps = min(bandwidth_kbps, self.chaos.bandwidth_cap_kbps)
        bandwidth_bps = max(bandwidth_kbps * 1000.0, 1.0)
        serialization_delay_ms = (packet.payload_size * 8 / bandwidth_bps) * 1000.0

        total = base_latency + jitter_sample + serialization_delay_ms
        return max(total, 0.1)  # never zero/negative -- keeps delivery strictly after send

    def _roll_reorder(self) -> bool:
        prob = self.conditions.reorder_probability_percent
        if self.chaos.reordering_enabled:
            prob = max(prob, 5.0)  # chaos mode guarantees a meaningfully observable rate
        return self._rng.random() * 100 < prob
