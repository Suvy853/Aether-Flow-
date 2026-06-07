# Aether-Flow

**Self-Healing MLOps Pipeline Orchestrator**

Aether-Flow is a production-grade agentic system that accepts a natural language goal, autonomously discovers heterogeneous data sources, decomposes the goal into an executable pipeline, generates and runs the required code, repairs failures without human intervention, and audits all outputs through a multimodal quality gate before deployment.

---

## Live Services

| Service | URL |
|---------|-----|
| REST API | https://web-production-f0ca5.up.railway.app |
| MLOps Dashboard | https://aether-flow-production.up.railway.app |
| Interactive API Docs | https://web-production-f0ca5.up.railway.app/docs |
| Live Telemetry | https://web-production-f0ca5.up.railway.app/telemetry/stats |

---

## System Overview

Aether-Flow operates as a closed-loop orchestration system across four sequential phases. Each phase is independently testable, fully logged to PostgreSQL, and designed to degrade gracefully under failure conditions.

**Phase 1 — Discovery Hub**
A FastMCP server probes all registered data sources and extracts structural metadata — table schemas, column statistics, row counts, and representative samples — without loading raw data. The resulting context summary is injected into the agent at approximately 500 tokens, regardless of underlying dataset size. Supported source types: PostgreSQL, CSV, and REST APIs.

**Phase 2 — Agentic Planner**
Claude, orchestrated by LangGraph, receives the metadata context and the user goal and decomposes it into a directed acyclic graph (DAG) of atomic, executable steps. Each step is assigned a source, operation type, dependency chain, and detailed execution specification. The plan is returned as structured JSON and validated before execution begins.

**Phase 3 — Self-Healing Execution**
For each step in the plan, the executor requests Python code from Claude, runs it in an isolated subprocess sandbox, and evaluates the result via a structured output marker. On failure, the complete traceback is returned to a dedicated repair agent alongside the original code and step context. The repair agent performs root cause analysis and generates a corrected implementation. This Reflexion loop runs up to three attempts per step. All repair events — including error type, line delta, and success outcome — are persisted to PostgreSQL for pattern analysis.

**Phase 4 — Multimodal Guardian**
Every chart or visual output produced by the pipeline is encoded and submitted to Claude Vision for quality audit. The Guardian evaluates data integrity, visual quality, business logic coherence, and task completeness, returning a structured verdict with confidence score and extracted metrics. Pipelines that fail the audit are blocked from deployment. All audit results are linked to the originating pipeline run via a shared UUID.

---

## Technical Architecture

```
User Goal (natural language)
          │
          ▼
┌─────────────────────┐
│   Discovery Hub     │  FastMCP · psycopg3 · requests
│   Phase 1           │  PostgreSQL + CSV + REST API
└────────┬────────────┘
         │ metadata context (~500 tokens)
         ▼
┌─────────────────────┐
│   Agentic Planner   │  LangGraph · Claude (claude-opus-4-6)
│   Phase 2           │  DAG decomposition · JSON plan
└────────┬────────────┘
         │ executable step plan
         ▼
┌─────────────────────┐
│  Self-Healing       │  subprocess sandbox · Reflexion loop
│  Executor           │  Code generation → execution → repair
│  Phase 3            │  Telemetry: repair_events · step_executions
└────────┬────────────┘
         │ pipeline results + chart outputs
         ▼
┌─────────────────────┐
│  Multimodal         │  Claude Vision · base64 image encoding
│  Guardian           │  Pass/Fail verdict · confidence score
│  Phase 4            │  Telemetry: guardian_audits
└────────┬────────────┘
         │ deployment decision
         ▼
┌─────────────────────┐
│  FastAPI + Dash     │  Async job execution · live telemetry
│  Dashboard          │  Repair patterns · run history · KPIs
└─────────────────────┘
          │
          ▼
   Railway (Production)
```

---

## Technology Stack

| Component | Technology |
|-----------|------------|
| LLM Provider | Anthropic Claude (claude-opus-4-6) |
| Agent Framework | LangGraph |
| Data Discovery Protocol | FastMCP |
| Database Driver | psycopg3 (binary) |
| Code Sandbox | Python subprocess + RestrictedPython |
| Self-Healing Algorithm | Reflexion (Shinn et al., 2023) |
| Visual QA | Claude Vision (multimodal) |
| API Framework | FastAPI + Uvicorn |
| Dashboard | Plotly Dash |
| Production Database | PostgreSQL on Railway |
| Deployment Platform | Railway |
| Primary Data Sources | Railway PostgreSQL (2.58M transactions), synthetic retail CSV, Open-Meteo weather API |

---

## MLOps Telemetry Schema

All pipeline activity is persisted to PostgreSQL and queryable via the telemetry API.

**pipeline_runs**
Stores one record per pipeline execution: goal, complexity classification, step counts, total repairs triggered, execution duration, and deployment approval status.

**step_executions**
Stores one record per step per run: step ID, task description, source type, operation type, attempt count, repair count, execution time, and error details on failure.

**repair_events**
Stores one record per repair attempt: run UUID, step ID, attempt number, error type extracted from traceback, full error message, repair outcome, and line count delta between original and repaired code.

**guardian_audits**
Stores one record per chart audited: run UUID, file path, verdict, confidence score, findings across four dimensions (data integrity, visual quality, business logic, completeness), and issues list.

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /pipeline/run | Submit a natural language goal and start a pipeline |
| GET | /pipeline/{job_id}/status | Poll the current phase and status of a running job |
| GET | /pipeline/{job_id}/result | Retrieve the full result of a completed job |
| GET | /telemetry/stats | Aggregated statistics across all pipeline runs |
| GET | /telemetry/runs | Recent runs with repair patterns |
| GET | /jobs | List all jobs in the current session |
| GET | /health | Service health check |

**Example request:**

```bash
curl -X POST https://web-production-f0ca5.up.railway.app/pipeline/run \
  -H "Content-Type: application/json" \
  -d '{"goal": "Fetch the top 5 transaction categories by total amount and visualize the results"}'
```

**Example response:**

```json
{
  "job_id": "job_20260607_120000_0",
  "status": "queued",
  "message": "Pipeline started. Poll /pipeline/{job_id}/status for updates.",
  "started_at": "2026-06-07T12:00:00.000000"
}
```

---

## Local Setup

**Prerequisites:** Python 3.11+, PostgreSQL instance, Anthropic API key

```bash
git clone https://github.com/Suvy853/Aether-Flow-.git
cd Aether-Flow-
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```
ANTHROPIC_API_KEY=your-anthropic-api-key
DATABASE_URL=postgresql://user:password@host:port/dbname
ENVIRONMENT=development
```

Initialise telemetry tables:

```bash
python setup_telemetry.py
```

Run the full pipeline with a default goal:

```bash
python main.py
```

Run in interactive mode:

```bash
python main.py --interactive
```

Run with a specific goal:

```bash
python main.py --goal "Analyze transaction volumes by region and visualize the breakdown"
```

Start the API server:

```bash
uvicorn src.api.routes:app --reload --port 8000
```

Start the dashboard (requires API running):

```bash
python src/ui/dashboard.py
```

---

## Repository Structure

```
aether-flow/
├── main.py                        # Four-phase pipeline orchestrator
├── start.py                       # Railway unified entry point
├── setup_telemetry.py             # PostgreSQL schema initialisation
├── requirements.txt
├── Procfile
├── railway.json
├── src/
│   ├── discovery/
│   │   └── mcp_server.py          # Phase 1: FastMCP source probing
│   ├── planner/
│   │   └── agent.py               # Phase 2: LangGraph DAG planner
│   ├── execution/
│   │   ├── executor.py            # Phase 3: Reflexion execution loop
│   │   └── telemetry.py           # PostgreSQL telemetry logger
│   ├── guardian/
│   │   └── auditor.py             # Phase 4: Vision quality gate
│   ├── api/
│   │   └── routes.py              # FastAPI async job endpoints
│   └── ui/
│       ├── dashboard.py           # Plotly Dash MLOps dashboard
│       └── dashboard_prod.py      # Production dashboard entry point
├── examples/
│   └── retail.csv                 # Sample retail transaction dataset
└── outputs/                       # Pipeline-generated chart outputs
```

---

## Example Goals

The following goals have been validated against the deployed system:

- Fetch the top 5 transaction categories by total amount from PostgreSQL and visualize the results
- Show customer segment distribution by risk tier from PostgreSQL as a pie chart
- Analyze transaction amounts by region from PostgreSQL and show regional breakdown
- Compare retail product category revenue from the CSV dataset and show top performers
- Analyze daily transaction volumes from PostgreSQL and correlate with weather temperature data

---

## Key Design Decisions

**Metadata-first discovery.** The agent never receives raw data rows. It operates exclusively on structural metadata, keeping token costs predictable regardless of dataset scale. A 2.58 million row PostgreSQL database and a 10,000 row CSV are both represented in approximately 500 tokens.

**Reflexion over retry.** Standard retry logic resubmits the same prompt and hopes for a different result. Reflexion feeds the failure artifact — the complete traceback, the broken code, and the step context — back to a specialized repair agent. The repair agent diagnoses root cause rather than surface symptoms, producing consistently higher repair success rates on subsequent attempts.

**Separation of cognitive roles.** Code generation and code repair are handled by separate system prompts with distinct instructions. The generator optimizes for correctness on the happy path; the repair agent optimizes for diagnosis under failure. Mixing these concerns degrades performance on both tasks.

**Vision-based quality gates.** Rather than relying on programmatic output validation, the Guardian submits rendered chart images to Claude Vision. This catches semantic errors — misleading scales, unlabeled axes, nonsensical distributions — that code-level validation cannot detect.

**Persistent telemetry.** Every run is fully logged to PostgreSQL with UUID linkage across all four tables. This enables cross-run analysis of repair patterns, error type frequencies, step reliability by operation type, and Guardian verdict trends over time.

---

## Author

Suveera Pratapa
Masters in Analytics — Northeastern University
GitHub: https://github.com/Suvy853