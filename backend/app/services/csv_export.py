"""Converts a list of `ExperimentResult`s into a comparison CSV."""
from __future__ import annotations

import csv
import io
from typing import List

from app.models.experiment import ExperimentResult

_FIELDS = [
    "experiment_name",
    "completed",
    "duration_ms",
    "packets_sent",
    "packets_delivered",
    "packets_lost",
    "packet_loss_rate_percent",
    "retransmissions",
    "fast_retransmits",
    "timeouts",
    "duplicate_acks",
    "rtt_avg_ms",
    "rtt_min_ms",
    "rtt_max_ms",
    "throughput_bps",
    "goodput_bps",
    "final_cwnd_segments",
]


def experiments_to_csv(results: List[ExperimentResult]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_FIELDS)
    writer.writeheader()
    for result in results:
        stats = result.final_statistics
        writer.writerow(
            {
                "experiment_name": result.definition.name,
                "completed": result.completed,
                "duration_ms": round(result.duration_ms, 2),
                "packets_sent": stats.packets_sent,
                "packets_delivered": stats.packets_delivered,
                "packets_lost": stats.packets_lost,
                "packet_loss_rate_percent": round(stats.packet_loss_rate_percent, 2),
                "retransmissions": stats.retransmissions,
                "fast_retransmits": stats.fast_retransmits,
                "timeouts": stats.timeouts,
                "duplicate_acks": stats.duplicate_acks,
                "rtt_avg_ms": round(stats.rtt_avg_ms, 2) if stats.rtt_avg_ms else "",
                "rtt_min_ms": round(stats.rtt_min_ms, 2) if stats.rtt_min_ms else "",
                "rtt_max_ms": round(stats.rtt_max_ms, 2) if stats.rtt_max_ms else "",
                "throughput_bps": round(stats.throughput_bps, 2),
                "goodput_bps": round(stats.goodput_bps, 2),
                "final_cwnd_segments": round(stats.current_cwnd_segments, 2),
            }
        )
    return buffer.getvalue()
