from __future__ import annotations

import json
import logging

from fastapi import WebSocket, WebSocketDisconnect

from app.simulation.session import SimulationSession
from app.websocket.connection_manager import connection_manager
from app.websocket.protocol import UnknownMessageTypeError, parse_client_message
from app.websocket.session_runner import LiveSessionRunner

logger = logging.getLogger(__name__)


async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()

    async def send(payload: dict) -> None:
        try:
            await websocket.send_text(json.dumps(payload))
        except RuntimeError:
            pass  # socket already closing

    runner = LiveSessionRunner(session_factory=SimulationSession, send=send)
    session_id = connection_manager.register(runner)

    await send({"type": "session_ready", "session_id": session_id})

    async def receive_loop() -> None:
        while True:
            raw_text = await websocket.receive_text()
            try:
                raw = json.loads(raw_text)
                message = parse_client_message(raw)
            except (json.JSONDecodeError, UnknownMessageTypeError, ValueError) as exc:
                await send({"type": "error", "message": str(exc)})
                continue
            runner.enqueue(message)

    try:
        import asyncio

        run_task = asyncio.create_task(runner.run())
        receive_task = asyncio.create_task(receive_loop())
        done, pending = await asyncio.wait(
            {run_task, receive_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc is not None and not isinstance(exc, WebSocketDisconnect):
                raise exc
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: session_id=%s", session_id)
    finally:
        connection_manager.remove(session_id)
