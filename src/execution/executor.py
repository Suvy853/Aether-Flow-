import os
import sys
import json
import time
import subprocess
import tempfile
from pathlib import Path
from anthropic import Anthropic
from dotenv import load_dotenv
from src.execution.telemetry import (
    generate_run_uuid,
    log_pipeline_run,
    log_step_execution,
    log_repair_event
)

load_dotenv()

client = Anthropic()

CODE_GEN_SYSTEM_PROMPT = """You are Aether-Flow's Code Generator. You generate clean, executable Python code for a single pipeline step.

Rules:
- Generate ONLY the Python code, no explanations, no markdown fences
- The code must be self-contained and executable as a script
- ALWAYS add 'import matplotlib; matplotlib.use("Agg")' as the very first matplotlib-related line before any other matplotlib or pyplot imports
- Always print a JSON result at the end using: print("AETHER_RESULT:" + json.dumps(result))
- The result dict must contain a 'status' key ('success' or 'error') and a 'summary' key
- For data results, include a 'data' key with a sample (max 10 rows as list of dicts)
- Import everything you need at the top
- Use environment variables for credentials via os.getenv()
- Handle exceptions with try/except and still print AETHER_RESULT on failure
- For file outputs (charts), include the filepath in result
- Always create the outputs directory with os.makedirs('outputs', exist_ok=True) before saving any file
- Keep code focused on exactly what the step requires"""

REPAIR_SYSTEM_PROMPT = """You are Aether-Flow's Code Repair Agent. You fix broken Python code.

You will receive:
1. The original code that failed
2. The error traceback
3. The step context

Rules:
- Return ONLY the fixed Python code, no explanations, no markdown fences
- Fix the root cause, not just the symptom
- Keep the same structure and logic, just fix what is broken
- ALWAYS include 'import matplotlib; matplotlib.use("Agg")' before any matplotlib imports
- Always end with print("AETHER_RESULT:" + json.dumps(result))
- Be precise, do not rewrite what works"""


def generate_code(step: dict, context_summary: str, previous_results: dict) -> str:
    """Ask Claude to generate Python code for a pipeline step."""

    prev_context = ""
    if previous_results:
        prev_context = "\nPrevious step results available:\n"
        for step_id, result in previous_results.items():
            if isinstance(result, dict):
                summary = result.get("summary", "")
                data_sample = result.get("data", [])[:2]
                prev_context += f"  {step_id}: {summary}\n"
                if data_sample:
                    prev_context += f"    Sample: {json.dumps(data_sample, default=str)}\n"

    prompt = f"""Generate Python code for this pipeline step:

Step ID: {step['id']}
Task: {step['task']}
Operation: {step['operation']}
Source: {step['source']}
Details: {step['details']}

Data context:
{context_summary}
{prev_context}

Environment variables available:
- DATABASE_URL: PostgreSQL connection string
- ANTHROPIC_API_KEY: Anthropic API key

Generate the complete executable Python script now."""

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=3000,
        system=CODE_GEN_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )

    code = response.content[0].text.strip() # pyright: ignore[reportAttributeAccessIssue]
    if code.startswith("```"):
        lines = code.split("\n")
        code = "\n".join(lines[1:-1])
    return code


def execute_code(code: str, step_id: str, timeout: int = 120) -> dict:
    """Execute generated code in a subprocess sandbox."""
    env = os.environ.copy()

    with tempfile.NamedTemporaryFile(
        mode='w',
        suffix='.py',
        delete=False,
        prefix=f'aether_{step_id}_'
    ) as f:
        f.write(code)
        temp_path = f.name

    try:
        result = subprocess.run(
            [sys.executable, temp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env
        )

        stdout = result.stdout
        stderr = result.stderr

        for line in stdout.split("\n"):
            if line.startswith("AETHER_RESULT:"):
                try:
                    return json.loads(line[len("AETHER_RESULT:"):])
                except json.JSONDecodeError:
                    pass

        return {
            "status": "error",
            "error": stderr or "No AETHER_RESULT found in output",
            "stdout": stdout,
            "summary": f"Step {step_id} produced no result marker"
        }

    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "error": f"Step {step_id} timed out after {timeout}s",
            "summary": "Execution timeout"
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "summary": f"Execution failed: {e}"
        }
    finally:
        os.unlink(temp_path)


def repair_code(code: str, error: str, step: dict) -> str:
    """Ask Claude to repair broken code using the error traceback."""

    prompt = f"""Fix this broken Python code:

STEP CONTEXT:
Task: {step['task']}
Details: {step['details']}

ORIGINAL CODE:
{code}

ERROR:
{error}

Return only the fixed Python code."""

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=3000,
        system=REPAIR_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )

    fixed = response.content[0].text.strip() # pyright: ignore[reportAttributeAccessIssue]
    if fixed.startswith("```"):
        lines = fixed.split("\n")
        fixed = "\n".join(lines[1:-1])
    return fixed


def execute_step_with_healing(
    step: dict,
    context_summary: str,
    previous_results: dict,
    run_uuid: str,
    max_retries: int = 3
) -> dict:
    """Execute a single pipeline step with automatic self-healing and telemetry."""
    print(f"\n  Executing [{step['id']}]: {step['task']}")

    step_start = time.time()
    repairs_triggered = 0
    final_error_type = None
    final_error_message = None

    code = generate_code(step, context_summary, previous_results)
    lines_of_code = len(code.split("\n"))
    print(f"     -> Code generated ({lines_of_code} lines)")

    for attempt in range(1, max_retries + 1):
        result = execute_code(code, step['id'])

        if result.get("status") == "success":
            print(f"     Success on attempt {attempt}: {result.get('summary', '')}")

            execution_time = time.time() - step_start
            log_step_execution(
                run_uuid=run_uuid,
                step_id=step['id'],
                task=step['task'],
                source=step['source'],
                operation=step['operation'],
                status="success",
                attempts=attempt,
                repairs_triggered=repairs_triggered,
                execution_time_seconds=execution_time,
                lines_of_code=lines_of_code
            )
            return result

        error = result.get("error", "Unknown error")
        print(f"     Attempt {attempt} failed: {error[:100]}...")
        final_error_message = error
        final_error_type = error.split("\n")[-1][:100] if error else "Unknown"

        if attempt < max_retries:
            lines_before = len(code.split("\n"))
            print(f"     Reflexion loop: repairing code...")

            log_repair_event(
                run_uuid=run_uuid,
                step_id=step['id'],
                attempt_number=attempt,
                error_type=final_error_type,
                error_message=error,
                repair_successful=False,
                lines_before=lines_before,
                lines_after=0
            )

            code = repair_code(code, error, step)
            lines_after = len(code.split("\n"))
            repairs_triggered += 1
            print(f"     Repaired code generated ({lines_after} lines)")

        else:
            print(f"     All {max_retries} attempts failed for [{step['id']}]")

            log_repair_event(
                run_uuid=run_uuid,
                step_id=step['id'],
                attempt_number=attempt,
                error_type=final_error_type,
                error_message=error,
                repair_successful=False,
                lines_before=lines_of_code,
                lines_after=0
            )

            execution_time = time.time() - step_start
            log_step_execution(
                run_uuid=run_uuid,
                step_id=step['id'],
                task=step['task'],
                source=step['source'],
                operation=step['operation'],
                status="failed",
                attempts=attempt,
                repairs_triggered=repairs_triggered,
                execution_time_seconds=execution_time,
                error_type=final_error_type,
                error_message=final_error_message,
                lines_of_code=lines_of_code
            )

            result["step_id"] = step['id']
            return result

    return result


def execute_pipeline(plan: dict, context_summary: str) -> tuple[dict, str]:
    """Execute all steps in the pipeline DAG with telemetry."""
    run_uuid = generate_run_uuid()
    pipeline_start = time.time()
    total_repairs = 0

    print(f"\n Starting pipeline execution: {len(plan['steps'])} steps")
    print(f"   Run ID: {run_uuid[:8]}...")
    print(f"   Complexity: {plan['estimated_complexity']}")

    results = {}
    failed_steps = []

    for step in plan['steps']:
        deps_ok = all(
            results.get(dep, {}).get("status") == "success"
            for dep in step.get("depends_on", [])
        )

        if not deps_ok:
            failed_deps = [
                dep for dep in step.get("depends_on", [])
                if results.get(dep, {}).get("status") != "success"
            ]
            print(f"\n  Skipping [{step['id']}]: dependencies failed: {failed_deps}")
            results[step['id']] = {
                "status": "skipped",
                "reason": f"Dependencies failed: {failed_deps}",
                "summary": "Step skipped due to upstream failure"
            }
            failed_steps.append(step['id'])
            continue

        result = execute_step_with_healing(
            step, context_summary, results, run_uuid
        )
        results[step['id']] = result

        if result.get("status") != "success":
            failed_steps.append(step['id'])

    for step in plan['steps']:
        step_result = results.get(step['id'], {})
        total_repairs += step_result.get("repairs_triggered", 0)

    succeeded = sum(1 for r in results.values() if r.get("status") == "success")
    execution_time = time.time() - pipeline_start

    log_pipeline_run(
        run_uuid=run_uuid,
        goal=plan['goal'],
        complexity=plan['estimated_complexity'],
        total_steps=len(plan['steps']),
        steps_succeeded=succeeded,
        steps_failed=len(failed_steps),
        deploy_approved=len(failed_steps) == 0,
        total_repairs=total_repairs,
        execution_time_seconds=execution_time
    )

    print(f"\n{'='*50}")
    print(f"PIPELINE COMPLETE: {succeeded}/{len(plan['steps'])} steps succeeded")
    print(f"Run ID: {run_uuid[:8]} | Time: {execution_time:.1f}s | Repairs: {total_repairs}")
    if failed_steps:
        print(f"Failed steps: {failed_steps}")
    print(f"{'='*50}")

    return results, run_uuid


if __name__ == "__main__":
    from src.discovery.mcp_server import discover_all_sources
    from src.planner.agent import plan_pipeline, print_plan

    context = discover_all_sources(csv_path="examples/retail.csv")

    goal = "Fetch the top 5 transaction categories by total amount from PostgreSQL and show the results"
    plan = plan_pipeline(goal, context["summary"])
    print_plan(plan)

    results, run_uuid = execute_pipeline(plan, context["summary"])

    print("\nFINAL RESULTS:")
    for step_id, result in results.items():
        status = result.get("status", "unknown")
        summary = result.get("summary", "")
        print(f"  [{step_id}] {status}: {summary}")

    from src.execution.telemetry import get_pipeline_stats
    stats = get_pipeline_stats()
    print(f"\nMLOps Telemetry:")
    print(f"  Total pipeline runs: {stats['overall']['total_runs']}")
    print(f"  Total repairs logged: {stats['overall']['total_repairs']}")
    print(f"  Avg execution time: {stats['overall']['avg_execution_time']}s")