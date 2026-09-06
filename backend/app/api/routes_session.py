from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.websocket.connection_manager import connection_manager

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("/{session_id}/state")
async def get_session_state(session_id: str) -> dict:
    """Lightweight polling fallback / debugging endpoint -- the live
    dashboard should prefer the WebSocket stream."""
    runner = connection_manager.get(session_id)
    if runner is None:
        raise HTTPException(status_code=404, detail="Session not found")
    session = runner.session
    return {
        "client_state": session.client_fsm.state.value,
        "server_state": session.server_fsm.state.value,
        "clock_ms": session.clock.now_ms,
        "is_paused": session.clock.is_paused,
        "speed_multiplier": session.clock.speed_multiplier,
        "stats": runner.statistics.stats.model_dump(mode="json"),
    }
