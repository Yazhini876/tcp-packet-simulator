"""Experiment Mode models: run named network-condition scenarios headlessly
and compare their outcomes."""
from __future__ import annotations

import uuid
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.connection import TCPConfig
from app.models.congestion import CongestionSample
from app.models.network_config import NetworkConditions
from app.models.statistics import SimulationStatistics


class ExperimentDefinition(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    name: str
    network_conditions: NetworkConditions
    tcp_config: TCPConfig = Field(default_factory=TCPConfig)
    message_payload: str
    max_virtual_time_ms: float = Field(
        default=30_000.0,
        description="Safety cap so a pathological config (e.g. 100% loss) can't run forever.",
    )
    seed: Optional[int] = None
    """If omitted, a seed is generated so results remain reproducible after the fact."""


class ExperimentResult(BaseModel):
    definition: ExperimentDefinition
    final_statistics: SimulationStatistics
    cwnd_history: List[CongestionSample]
    duration_ms: float
    completed: bool
    """False if the run hit `max_virtual_time_ms` without reaching CLOSED on
    both endpoints -- surfaced in the UI rather than silently truncated."""
