from __future__ import annotations

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from app.api import routes_experiments, routes_session
from app.config import settings
from app.websocket.handlers import websocket_endpoint

app = FastAPI(
    title="TCP Network Lab API",
    description=(
        "Backend simulation engine for TCP Network Lab. Simulates TCP "
        "connection behavior in software (no real sockets) so packet loss, "
        "latency, congestion control, and retransmission can be controlled "
        "deterministically for teaching purposes."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_experiments.router)
app.include_router(routes_session.router)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


@app.websocket("/ws/sessions")
async def ws_sessions(websocket: WebSocket) -> None:
    await websocket_endpoint(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
