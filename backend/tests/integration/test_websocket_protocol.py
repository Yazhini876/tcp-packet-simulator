"""End-to-end test of the WebSocket protocol: connect, start a simulation,
send data, close it, and verify we receive the expected event stream --
exercising `app.main`, `websocket/handlers.py`, and `session_runner.py`
together rather than mocking any of them.

Reads use a hard wall-clock timeout (via a worker thread) rather than a
fixed message count: the live protocol naturally goes idle between
"interesting" events (e.g. waiting out an RTO that never fires because
everything was ACKed), and a fixed count that overshoots what a given
run actually produces would hang forever on a blocking `receive_text()`.
"""
from __future__ import annotations

import json
import queue
import threading

from fastapi.testclient import TestClient

from app.main import app

_READ_TIMEOUT_S = 3.0


def _try_receive(ws, timeout: float = _READ_TIMEOUT_S):
    """Read one message with a hard wall-clock timeout that never blocks
    on cleanup. `ThreadPoolExecutor.__exit__` waits for its worker thread
    to finish by default even after `future.result(timeout=...)` gives up
    -- since a timed-out `receive_text()` call stays blocked forever with
    nothing more arriving, that wait never returns. A raw daemon thread
    with a result queue avoids that: we simply stop watching it.
    """
    result_q: "queue.Queue" = queue.Queue(maxsize=1)

    def worker():
        try:
            result_q.put(("ok", ws.receive_text()))
        except Exception as exc:  # noqa: BLE001 - propagate anything to the queue
            result_q.put(("error", exc))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    try:
        status, value = result_q.get(timeout=timeout)
    except queue.Empty:
        return None
    if status == "error":
        raise value
    return value


def _collect_until(ws, wanted_types: set[str], max_reads: int = 60, timeout: float = _READ_TIMEOUT_S) -> list[dict]:
    """Read messages until every type in `wanted_types` has been seen at
    least once, a hard read timeout elapses, or `max_reads` is hit."""
    seen: list[dict] = []
    found: set[str] = set()
    for _ in range(max_reads):
        raw = _try_receive(ws, timeout)
        if raw is None:
            break
        data = json.loads(raw)
        seen.append(data)
        found.add(data["type"])
        if wanted_types <= found:
            break
    return seen


def test_session_ready_on_connect():
    client = TestClient(app)
    with client.websocket_connect("/ws/sessions") as ws:
        first = json.loads(ws.receive_text())
        assert first["type"] == "session_ready"
        assert "session_id" in first


def test_start_simulation_reaches_established():
    client = TestClient(app)
    with client.websocket_connect("/ws/sessions") as ws:
        ws.receive_text()  # session_ready
        ws.send_text(json.dumps({"type": "update_network_config", "payload": {"latency_ms": 1.0, "jitter_ms": 0.0}}))
        ws.receive_text()  # ack (stats_snapshot)
        ws.send_text(json.dumps({"type": "start_simulation"}))

        seen = _collect_until(ws, {"connection_established"})
        seen_types = [m["type"] for m in seen]
        assert "connection_established" in seen_types
        assert "packet_sent" in seen_types
        assert "packet_delivered" in seen_types
        state_changes = [m for m in seen if m["type"] == "state_changed"]
        assert len(state_changes) >= 3


def test_unknown_message_type_returns_error():
    client = TestClient(app)
    with client.websocket_connect("/ws/sessions") as ws:
        ws.receive_text()  # session_ready
        ws.send_text(json.dumps({"type": "not_a_real_message"}))
        response = json.loads(ws.receive_text())
        assert response["type"] == "error"


def test_send_message_after_established_produces_data_packets():
    client = TestClient(app)
    with client.websocket_connect("/ws/sessions") as ws:
        ws.receive_text()  # session_ready
        ws.send_text(json.dumps({"type": "update_network_config", "payload": {"latency_ms": 1.0, "jitter_ms": 0.0}}))
        ws.receive_text()
        ws.send_text(json.dumps({"type": "start_simulation"}))
        established_batch = _collect_until(ws, {"connection_established"})
        assert "connection_established" in [m["type"] for m in established_batch]

        ws.send_text(json.dumps({"type": "send_message", "payload": "HI TCP"}))
        data_batch = _collect_until(ws, {"packet_sent"})
        data_packets = [
            m for m in data_batch
            if m["type"] == "packet_sent" and m["packet"]["packet_type"] == "DATA"
        ]
        assert len(data_packets) >= 1


def test_pause_stops_new_events_from_arriving():
    client = TestClient(app)
    with client.websocket_connect("/ws/sessions") as ws:
        ws.receive_text()  # session_ready
        ws.send_text(json.dumps({
            "type": "update_network_config",
            "payload": {"latency_ms": 300.0, "jitter_ms": 0.0},
        }))
        ws.receive_text()
        ws.send_text(json.dumps({"type": "pause_simulation"}))
        ws.receive_text()  # ack
        ws.send_text(json.dumps({"type": "start_simulation"}))

        # `start_simulation` transitions server (CLOSED->LISTEN) and client
        # (CLOSED->SYN_SENT) FSMs -- two state_changed events -- and only
        # then builds and sends the SYN (packet_sent). All three arrive in
        # the same flushed batch, before the delivery event that the pause
        # should be blocking.
        batch = []
        for _ in range(3):
            batch.append(json.loads(ws.receive_text())["type"])
        assert batch.count("state_changed") == 2
        assert "packet_sent" in batch
        stalled = _try_receive(ws, timeout=1.0)
        # Only the stats_snapshot from the start command itself should
        # follow; nothing else should arrive while paused.
        if stalled is not None:
            assert json.loads(stalled)["type"] == "stats_snapshot"
        again = _try_receive(ws, timeout=1.0)
        assert again is None  # confirms the pause actually held the clock
