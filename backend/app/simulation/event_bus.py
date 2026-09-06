"""Minimal synchronous pub/sub used internally by the simulation engine.

Kept deliberately tiny: the engine only needs "publish an event, notify
subscribers in registration order, synchronously." Subscribers (the
statistics engine, the WebSocket manager in Phase 3, test spies) never
mutate engine state -- they only observe.
"""
from __future__ import annotations

from typing import Callable, List

from app.models.events import SimulationEvent

Subscriber = Callable[[SimulationEvent], None]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: List[Subscriber] = []

    def subscribe(self, subscriber: Subscriber) -> None:
        self._subscribers.append(subscriber)

    def unsubscribe(self, subscriber: Subscriber) -> None:
        if subscriber in self._subscribers:
            self._subscribers.remove(subscriber)

    def publish(self, event: SimulationEvent) -> None:
        for subscriber in list(self._subscribers):
            subscriber(event)
