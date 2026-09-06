"""Generic event-driven scheduler keyed by virtual time.

Deliberately generic (not packet-specific) so it can schedule both packet
delivery events and periodic "check for expired RTOs" events on the same
timeline. This mirrors classic discrete-event simulation design: nothing
happens between events, so the engine can jump straight from one due event
to the next instead of ticking at a fixed interval.
"""
from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(order=True)
class ScheduledEvent:
    due_time_ms: float
    _seq: int = field(compare=True)
    kind: str = field(compare=False)
    payload: Any = field(compare=False)


class Scheduler:
    def __init__(self) -> None:
        self._heap: list[ScheduledEvent] = []
        self._counter = itertools.count()

    def push(self, due_time_ms: float, kind: str, payload: Any) -> None:
        """Schedule an event. `kind` distinguishes event categories the
        session cares about (e.g. 'packet_delivery', 'rto_check',
        'time_wait_expiry'). Ties in `due_time_ms` are broken by insertion
        order, guaranteeing determinism given a fixed sequence of pushes.
        """
        heapq.heappush(
            self._heap,
            ScheduledEvent(due_time_ms=due_time_ms, _seq=next(self._counter), kind=kind, payload=payload),
        )

    def peek_next_time(self) -> Optional[float]:
        return self._heap[0].due_time_ms if self._heap else None

    def pop_next(self) -> Optional[ScheduledEvent]:
        if not self._heap:
            return None
        return heapq.heappop(self._heap)

    @property
    def is_empty(self) -> bool:
        return not self._heap

    def __len__(self) -> int:
        return len(self._heap)
