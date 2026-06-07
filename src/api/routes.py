import os
import json
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.wsgi import WSGIMiddleware
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(
    title="Aether-Flow API",
    description="Self-Healing MLOps Pipeline Orchestrator",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from flask import Flask
from src.ui.dashboard import create_dash_app

flask_server = Flask(__name__)
dash_app = create_dash_app(server=flask_server, url_base_pathname="/dashboard/")
app.mount("/dashboard", WSGIMiddleware(flask_server))
app.mount("/_dash-component-suites", WSGIMiddleware(flask_server))
app.mount("/_dash-layout", WSGIMiddleware(flask_server))
app.mount("/_dash-dependencies", WSGIMiddleware(flask_server))
app.mount("/_dash-update-component", WSGIMiddleware(flask_server))
app.mount("/_reload-hash", WSGIMiddleware(flask_server))

jobs = {}


class PipelineRequest(BaseModel):
    goal: str
    csv_path: Optional[str] = "examples/retail.csv"


@app.get("/")
def root():
    return {
        "name": "Aether-Flow",
        "version": "1.0.0",
        "description": "Self-Healing MLOps Pipeline Orchestrator",
        "dashboard": "/dashboard/",
        "endpoints": {
            "POST /pipeline/run": "Start a new pipeline",
            "GET /pipeline/{job_id}/status": "Check pipeline status",
            "GET /pipeline/{job_id}/result": "Get pipeline result",
            "GET /telemetry/stats": "MLOps telemetry stats",
            "GET /telemetry/runs": "Recent pipeline runs",
            "GET /health": "Health check"
        }
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat()
    }


def run_pipeline_task(goal: str, csv_path: str, run_uuid_placeholder: str):
    try:
        jobs[run_uuid_placeholder]["status"] = "running"
        jobs[run_uuid_placeholder]["phase"] = "discovery"

        from src.discovery.mcp_server import discover_all_sources
        context = discover_all_sources(csv_path=csv_path)
        jobs[run_uuid_placeholder]["phase"] = "planning"

        from src.planner.agent import plan_pipeline
        plan = plan_pipeline(goal, context["summary"])

        if "error" in plan:
            jobs[run_uuid_placeholder]["status"] = "failed"
            jobs[run_uuid_placeholder]["error"] = plan["error"]
            return

        jobs[run_uuid_placeholder]["phase"] = "executing"
        jobs[run_uuid_placeholder]["plan"] = plan

        from src.execution.executor import execute_pipeline
        results, run_uuid = execute_pipeline(plan, context["summary"])

        jobs[run_uuid_placeholder]["phase"] = "auditing"
        jobs[run_uuid_placeholder]["run_uuid"] = run_uuid

        from src.guardian.auditor import audit_pipeline_outputs
        report = audit_pipeline_outputs(results, plan, goal, run_uuid)

        succeeded = sum(1 for r in results.values() if r.get("status") == "success")

        jobs[run_uuid_placeholder]["status"] = "complete"
        jobs[run_uuid_placeholder]["phase"] = "complete"
        jobs[run_uuid_placeholder]["run_uuid"] = run_uuid
        jobs[run_uuid_placeholder]["result"] = {
            "goal": goal,
            "steps_succeeded": succeeded,
            "total_steps": len(plan["steps"]),
            "deploy_approved": report["deploy_approved"],
            "overall_verdict": report["overall_verdict"],
            "charts_audited": report["total_charts"],
            "charts_passed": report["passed"],
            "completed_at": datetime.now().isoformat()
        }

    except Exception as e:
        jobs[run_uuid_placeholder]["status"] = "failed"
        jobs[run_uuid_placeholder]["error"] = str(e)


@app.post("/pipeline/run")
def run_pipeline(request: PipelineRequest, background_tasks: BackgroundTasks):
    if not request.goal.strip():
        raise HTTPException(status_code=400, detail="Goal cannot be empty")

    job_id = f"job_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(jobs)}"

    jobs[job_id] = {
        "job_id": job_id,
        "goal": request.goal,
        "status": "queued",
        "phase": "queued",
        "started_at": datetime.now().isoformat(),
        "run_uuid": None,
        "result": None,
        "error": None
    }

    background_tasks.add_task(
        run_pipeline_task,
        request.goal,
        request.csv_path, # pyright: ignore[reportArgumentType]
        job_id
    )

    return {
        "job_id": job_id,
        "status": "queued",
        "message": "Pipeline started. Poll /pipeline/{job_id}/status for updates.",
        "started_at": jobs[job_id]["started_at"]
    }


@app.get("/pipeline/{job_id}/status")
def get_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    job = jobs[job_id]
    return {
        "job_id": job_id,
        "status": job["status"],
        "phase": job["phase"],
        "goal": job["goal"],
        "started_at": job["started_at"],
        "run_uuid": job.get("run_uuid"),
        "error": job.get("error")
    }


@app.get("/pipeline/{job_id}/result")
def get_result(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    job = jobs[job_id]
    if job["status"] != "complete":
        return {
            "job_id": job_id,
            "status": job["status"],
            "phase": job["phase"],
            "message": "Pipeline not yet complete."
        }
    return {
        "job_id": job_id,
        "status": "complete",
        "run_uuid": job.get("run_uuid"),
        "result": job.get("result")
    }


@app.get("/telemetry/stats")
def telemetry_stats():
    from src.execution.telemetry import get_pipeline_stats
    stats = get_pipeline_stats()
    if "error" in stats:
        raise HTTPException(status_code=500, detail=stats["error"])
    return stats


@app.get("/telemetry/runs")
def recent_runs():
    from src.execution.telemetry import get_pipeline_stats
    stats = get_pipeline_stats()
    return {
        "recent_runs": stats.get("recent_runs", []),
        "repair_patterns": stats.get("repair_patterns", [])
    }


@app.get("/jobs")
def list_jobs():
    return {
        "total": len(jobs),
        "jobs": [
            {
                "job_id": jid,
                "status": j["status"],
                "phase": j["phase"],
                "goal": j["goal"][:60],
                "started_at": j["started_at"]
            }
            for jid, j in jobs.items()
        ]
    }