import psycopg
import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL: Optional[str] = os.getenv("DATABASE_URL")

CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id SERIAL PRIMARY KEY,
    run_uuid VARCHAR(36) NOT NULL,
    goal TEXT NOT NULL,
    complexity VARCHAR(20),
    total_steps INTEGER,
    steps_succeeded INTEGER,
    steps_failed INTEGER,
    deploy_approved BOOLEAN,
    total_tokens_used INTEGER DEFAULT 0,
    total_repairs INTEGER DEFAULT 0,
    execution_time_seconds FLOAT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS step_executions (
    execution_id SERIAL PRIMARY KEY,
    run_uuid VARCHAR(36) NOT NULL,
    step_id VARCHAR(50) NOT NULL,
    task TEXT,
    source VARCHAR(50),
    operation VARCHAR(50),
    status VARCHAR(20),
    attempts INTEGER DEFAULT 1,
    repairs_triggered INTEGER DEFAULT 0,
    execution_time_seconds FLOAT,
    error_type VARCHAR(100),
    error_message TEXT,
    lines_of_code INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS repair_events (
    repair_id SERIAL PRIMARY KEY,
    run_uuid VARCHAR(36) NOT NULL,
    step_id VARCHAR(50) NOT NULL,
    attempt_number INTEGER,
    error_type VARCHAR(100),
    error_message TEXT,
    repair_successful BOOLEAN,
    lines_before INTEGER,
    lines_after INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS guardian_audits (
    audit_id SERIAL PRIMARY KEY,
    run_uuid VARCHAR(36) NOT NULL,
    chart_filepath TEXT,
    verdict VARCHAR(10),
    confidence FLOAT,
    data_integrity_note TEXT,
    visual_quality_note TEXT,
    business_logic_note TEXT,
    issues_found TEXT,
    deploy_approved BOOLEAN,
    created_at TIMESTAMP DEFAULT NOW()
);
"""

def setup_telemetry():
    print("Setting up Aether-Flow telemetry tables...")
    try:
        with psycopg.connect(DATABASE_URL) as conn:  # type: ignore[arg-type]
            with conn.cursor() as cur:
                cur.execute(CREATE_TABLES)
            conn.commit()
        print("✓ pipeline_runs table created")
        print("✓ step_executions table created")
        print("✓ repair_events table created")
        print("✓ guardian_audits table created")
        print("\n✅ Telemetry setup complete.")
    except Exception as e:
        print(f"✗ Error: {e}")

if __name__ == "__main__":
    setup_telemetry()