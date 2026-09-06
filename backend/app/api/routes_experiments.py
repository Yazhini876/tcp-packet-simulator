from __future__ import annotations

from typing import List

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app.models.experiment import ExperimentDefinition, ExperimentResult
from app.services.csv_export import experiments_to_csv
from app.services.experiment_runner import run_experiments

router = APIRouter(prefix="/api/experiments", tags=["experiments"])


class RunExperimentsRequest(BaseModel):
    experiments: List[ExperimentDefinition]


class RunExperimentsResponse(BaseModel):
    results: List[ExperimentResult]


@router.post("/run", response_model=RunExperimentsResponse)
async def run(request: RunExperimentsRequest) -> RunExperimentsResponse:
    results = await run_experiments(request.experiments)
    return RunExperimentsResponse(results=results)


class ExportCsvRequest(BaseModel):
    results: List[ExperimentResult]


@router.post("/export-csv")
async def export_csv(request: ExportCsvRequest) -> PlainTextResponse:
    csv_text = experiments_to_csv(request.results)
    return PlainTextResponse(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=experiment_results.csv"},
    )
