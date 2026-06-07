import os
import uuid
import psycopg
from typing import Optional
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL: Optional[str] = os.getenv("DATABASE_URL")


def generate_run_uuid() -> str:
    """Generate a unique ID for each pipeline run."""
    return str(uuid.uuid4())


def log_pipeline_run(
    run_uuid: str,
    goal: str,
    complexity: str,
    total_steps: int,
    steps_succeeded: int,
    steps_failed: int,
    deploy_approved: bool,
    total_repairs: int,
    execution_time_seconds: float
):
    """Log a completed pipeline run to PostgreSQL."""
    try:
        with psycopg.connect(DATABASE_URL) as conn:  # type: ignore[arg-type]
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO pipeline_runs (
                        run_uuid, goal, complexity, total_steps,
                        steps_succeeded, steps_failed, deploy_approved,
                        total_repairs, execution_time_seconds
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    run_uuid, goal, complexity, total_steps,
                    steps_succeeded, steps_failed, deploy_approved,
                    total_repairs, execution_time_seconds
                ))
            conn.commit()
    except Exception as e:
        print(f"  ⚠️  Telemetry warning (pipeline_run): {e}")


def log_step_execution(
    run_uuid: str,
    step_id: str,
    task: str,
    source: str,
    operation: str,
    status: str,
    attempts: int,
    repairs_triggered: int,
    execution_time_seconds: float,
    error_type: Optional[str] = None,
    error_message: Optional[str] = None,
    lines_of_code: int = 0
):
    """Log a single step execution to PostgreSQL."""
    try:
        with psycopg.connect(DATABASE_URL) as conn:  # type: ignore[arg-type]
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO step_executions (
                        run_uuid, step_id, task, source, operation,
                        status, attempts, repairs_triggered,
                        execution_time_seconds, error_type,
                        error_message, lines_of_code
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    run_uuid, step_id, task, source, operation,
                    status, attempts, repairs_triggered,
                    execution_time_seconds, error_type,
                    error_message[:500] if error_message else None,
                    lines_of_code
                ))
            conn.commit()
    except Exception as e:
        print(f"  ⚠️  Telemetry warning (step_execution): {e}")


def log_repair_event(
    run_uuid: str,
    step_id: str,
    attempt_number: int,
    error_type: str,
    error_message: str,
    repair_successful: bool,
    lines_before: int,
    lines_after: int
):
    """Log a repair event to PostgreSQL."""
    try:
        # Extract error type from traceback
        error_type_clean = error_type
        if error_message and "Error" in error_message:
            for line in error_message.split("\n"):
                if "Error" in line or "Exception" in line:
                    error_type_clean = line.strip()[:100]
                    break

        with psycopg.connect(DATABASE_URL) as conn:  # type: ignore[arg-type]
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO repair_events (
                        run_uuid, step_id, attempt_number,
                        error_type, error_message, repair_successful,
                        lines_before, lines_after
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    run_uuid, step_id, attempt_number,
                    error_type_clean,
                    error_message[:500] if error_message else None,
                    repair_successful, lines_before, lines_after
                ))
            conn.commit()
    except Exception as e:
        print(f"  ⚠️  Telemetry warning (repair_event): {e}")


def log_guardian_audit(
    run_uuid: str,
    chart_filepath: str,
    verdict: str,
    confidence: float,
    findings: dict,
    issues: list,
    deploy_approved: bool
):
    """Log a Guardian audit result to PostgreSQL."""
    try:
        with psycopg.connect(DATABASE_URL) as conn:  # type: ignore[arg-type]
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO guardian_audits (
                        run_uuid, chart_filepath, verdict, confidence,
                        data_integrity_note, visual_quality_note,
                        business_logic_note, issues_found, deploy_approved
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    run_uuid,
                    chart_filepath,
                    verdict,
                    confidence,
                    findings.get("data_integrity", "")[:500],
                    findings.get("visual_quality", "")[:500],
                    findings.get("business_logic", "")[:500],
                    "; ".join(issues)[:500] if issues else None,
                    deploy_approved
                ))
            conn.commit()
    except Exception as e:
        print(f"  ⚠️  Telemetry warning (guardian_audit): {e}")


def get_pipeline_stats() -> dict:
    """
    Retrieve aggregated pipeline statistics.
    This powers the MLOps monitoring dashboard.
    """
    try:
        with psycopg.connect(DATABASE_URL) as conn:  # type: ignore[arg-type]
            with conn.cursor() as cur:

                # Overall run stats
                cur.execute("""
                    SELECT
                        COUNT(*) as total_runs,
                        SUM(steps_succeeded) as total_steps_succeeded,
                        SUM(total_repairs) as total_repairs,
                        AVG(execution_time_seconds) as avg_execution_time,
                        SUM(CASE WHEN deploy_approved THEN 1 ELSE 0 END) as approved_runs
                    FROM pipeline_runs;
                """)
                row = cur.fetchone() or (0, 0, 0, 0, 0)
                overall = {
                    "total_runs": row[0] or 0,
                    "total_steps_succeeded": row[1] or 0,
                    "total_repairs": row[2] or 0,
                    "avg_execution_time": round(row[3] or 0, 2),
                    "approved_runs": row[4] or 0
                }

                # Repair success rate by error type
                cur.execute("""
                    SELECT
                        error_type,
                        COUNT(*) as occurrences,
                        SUM(CASE WHEN repair_successful THEN 1 ELSE 0 END) as repaired,
                        ROUND(
                            100.0 * SUM(CASE WHEN repair_successful THEN 1 ELSE 0 END) / COUNT(*),
                            1
                        ) as repair_rate
                    FROM repair_events
                    WHERE error_type IS NOT NULL
                    GROUP BY error_type
                    ORDER BY occurrences DESC
                    LIMIT 10;
                """)
                repair_patterns = [
                    {
                        "error_type": r[0],
                        "occurrences": r[1],
                        "repaired": r[2],
                        "repair_rate": float(r[3]) if r[3] else 0
                    }
                    for r in cur.fetchall()
                ]

                # Recent runs
                cur.execute("""
                    SELECT run_uuid, goal, steps_succeeded,
                           total_steps, total_repairs,
                           deploy_approved, execution_time_seconds,
                           created_at
                    FROM pipeline_runs
                    ORDER BY created_at DESC
                    LIMIT 5;
                """)
                recent_runs = [
                    {
                        "run_uuid": r[0][:8],
                        "goal": r[1][:60],
                        "steps_succeeded": r[2],
                        "total_steps": r[3],
                        "total_repairs": r[4],
                        "deploy_approved": r[5],
                        "execution_time": round(r[6] or 0, 1),
                        "created_at": str(r[7])
                    }
                    for r in cur.fetchall()
                ]

        return {
            "overall": overall,
            "repair_patterns": repair_patterns,
            "recent_runs": recent_runs
        }

    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    stats = get_pipeline_stats()
    print("Pipeline Stats:")
    print(f"  Total runs: {stats['overall']['total_runs']}")
    print(f"  Total repairs: {stats['overall']['total_repairs']}")
    print(f"  Avg execution time: {stats['overall']['avg_execution_time']}s")