"""Client -> server WebSocket message envelopes.

Each message is a small discriminated-union member keyed on `type`. Kept
deliberately permissive on the `payload`/config dicts (partial updates)
since the underlying Pydantic config models validate the merged result
before it's applied -- see `handlers.py`.
"""
from __future__ import annotations

from typing import Any, Dict, Literal, Union

from pydantic import BaseModel


class StartSimulationMsg(BaseModel):
    type: Literal["start_simulation"] = "start_simulation"


class PauseSimulationMsg(BaseModel):
    type: Literal["pause_simulation"] = "pause_simulation"


class ResumeSimulationMsg(BaseModel):
    type: Literal["resume_simulation"] = "resume_simulation"


class ResetSimulationMsg(BaseModel):
    type: Literal["reset_simulation"] = "reset_simulation"


class SetSpeedMsg(BaseModel):
    type: Literal["set_speed"] = "set_speed"
    multiplier: float


class UpdateNetworkConfigMsg(BaseModel):
    type: Literal["update_network_config"] = "update_network_config"
    payload: Dict[str, Any]


class UpdateTcpConfigMsg(BaseModel):
    type: Literal["update_tcp_config"] = "update_tcp_config"
    payload: Dict[str, Any]


class SendMessageMsg(BaseModel):
    type: Literal["send_message"] = "send_message"
    payload: str


class CloseConnectionMsg(BaseModel):
    type: Literal["close_connection"] = "close_connection"


class ToggleChaosConditionMsg(BaseModel):
    type: Literal["toggle_chaos_condition"] = "toggle_chaos_condition"
    condition: str
    enabled: bool


class ToggleExplainModeMsg(BaseModel):
    type: Literal["toggle_explain_mode"] = "toggle_explain_mode"
    enabled: bool


ClientMessage = Union[
    StartSimulationMsg,
    PauseSimulationMsg,
    ResumeSimulationMsg,
    ResetSimulationMsg,
    SetSpeedMsg,
    UpdateNetworkConfigMsg,
    UpdateTcpConfigMsg,
    SendMessageMsg,
    CloseConnectionMsg,
    ToggleChaosConditionMsg,
    ToggleExplainModeMsg,
]

_MESSAGE_TYPES: Dict[str, type[BaseModel]] = {
    "start_simulation": StartSimulationMsg,
    "pause_simulation": PauseSimulationMsg,
    "resume_simulation": ResumeSimulationMsg,
    "reset_simulation": ResetSimulationMsg,
    "set_speed": SetSpeedMsg,
    "update_network_config": UpdateNetworkConfigMsg,
    "update_tcp_config": UpdateTcpConfigMsg,
    "send_message": SendMessageMsg,
    "close_connection": CloseConnectionMsg,
    "toggle_chaos_condition": ToggleChaosConditionMsg,
    "toggle_explain_mode": ToggleExplainModeMsg,
}


class UnknownMessageTypeError(Exception):
    def __init__(self, type_value: Any) -> None:
        super().__init__(f"Unknown client message type: {type_value!r}")


def parse_client_message(raw: Dict[str, Any]) -> ClientMessage:
    type_value = raw.get("type")
    model_cls = _MESSAGE_TYPES.get(type_value)
    if model_cls is None:
        raise UnknownMessageTypeError(type_value)
    return model_cls.model_validate(raw)
