"""Tracks live `LiveSessionRunner`s keyed by session id.

One session id maps to exactly one browser tab's simulation. Sessions are
purely in-memory (see Phase 1 architecture doc, Section 9 -- an accepted
MVP tradeoff); they disappear on server restart or explicit disconnect.
"""
from __future__ import annotations

import uuid
from typing import Dict

from app.websocket.session_runner import LiveSessionRunner


class ConnectionManager:
    def __init__(self) -> None:
        self._runners: Dict[str, LiveSessionRunner] = {}

    def register(self, runner: LiveSessionRunner) -> str:
        session_id = str(uuid.uuid4())
        self._runners[session_id] = runner
        return session_id

    def get(self, session_id: str) -> LiveSessionRunner | None:
        return self._runners.get(session_id)

    def remove(self, session_id: str) -> None:
        runner = self._runners.pop(session_id, None)
        if runner is not None:
            runner.stop()

    def __len__(self) -> int:
        return len(self._runners)


connection_manager = ConnectionManager()
