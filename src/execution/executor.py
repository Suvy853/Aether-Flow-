import os
import sys
import json
import subprocess
import tempfile
import textwrap
from typing import cast
from anthropic import Anthropic
from anthropic.types.text_block import TextBlock
from anthropic.types.thinking_block import ThinkingBlock
from dotenv import load_dotenv

load_dotenv()

client = Anthropic()

CODE_GEN_SYSTEM_PROMPT = """You are Aether-Flow's Code Generator. You generate clean, executable Python code for a single pipeline step.

Rules:
- Generate ONLY the Python code, no explanations, no markdown fences
- The code must be self-contained and executable as a script
- Always print a JSON result at the end using: print("AETHER_RESULT:" + json.dumps(result))
- The result dict must contain a 'status' key ('success' or 'error') and a 'summary' key
- For data results, include a 'data' key with a sample (max 10 rows as list of dicts)
- Import everything you need at the top
- Use environment variables for credentials via os.getenv()
- Handle exceptions with try/except and still print AETHER_RESULT on failure
- For file outputs (charts), include the filepath in result
- Keep code focused on exactly what the step requires"""

REPAIR_SYSTEM_PROMPT = """You are Aether-Flow's Code Repair Agent. You fix broken Python code.

You will receive:
1. The original code that failed
2. The error traceback
3. The step context

Rules:
- Return ONLY the fixed Python code, no explanations, no markdown fences
- Fix the root cause, not just the symptom
- Keep the same structure and logic, just fix what's broken
- Always end with print("AETHER_RESULT:" + json.dumps(result))
- Be precise — don't rewrite what works"""


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

    first_block = response.content[0]
    if first_block.type == "text":
        code = cast(TextBlock, first_block).text.strip()
    elif first_block.type == "thinking":
        code = cast(ThinkingBlock, first_block).thinking.strip()
    else:
        code = ""

    if code.startswith("```"):
        lines = code.split("\n")
        code = "\n".join(lines[1:-1])
    return code


def execute_code(code: str, step_id: str, timeout: int = 60) -> dict:
    """
    Execute generated code in a subprocess sandbox.
    Returns parsed result dict.
    """
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

        # Extract AETHER_RESULT from stdout
        for line in stdout.split("\n"):
            if line.startswith("AETHER_RESULT:"):
                try:
                    return json.loads(line[len("AETHER_RESULT:"):])
                except json.JSONDecodeError:
                    pass

        # If no result marker found, it's a failure
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

    first_block = response.content[0]
    if first_block.type == "text":
        fixed = cast(TextBlock, first_block).text.strip()
    elif first_block.type == "thinking":
        fixed = cast(ThinkingBlock, first_block).thinking.strip()
    else:
        fixed = ""

    if fixed.startswith("```"):
        lines = fixed.split("\n")
        fixed = "\n".join(lines[1:-1])
    return fixed


def execute_step_with_healing(
    step: dict,
    context_summary: str,
    previous_results: dict,
    max_retries: int = 3
) -> dict:
    """
    Execute a single pipeline step with automatic self-healing.
    Retries up to max_retries times on failure.
    """
    print(f"\n  ⚙️  Executing [{step['id']}]: {step['task']}")

    code = generate_code(step, context_summary, previous_results)
    print(f"     → Code generated ({len(code.split(chr(10)))} lines)")

    for attempt in range(1, max_retries + 1):
        result = execute_code(code, step['id'])

        if result.get("status") == "success":
            print(f"     ✓ Success on attempt {attempt}: {result.get('summary', '')}")
            return result

        error = result.get("error", "Unknown error")
        print(f"     ✗ Attempt {attempt} failed: {error[:100]}...")

        if attempt < max_retries:
            print(f"     🔧 Reflexion loop: repairing code...")
            code = repair_code(code, error, step)
            print(f"     → Repaired code generated ({len(code.split(chr(10)))} lines)")
        else:
            print(f"     ✗ All {max_retries} attempts failed for [{step['id']}]")
            result["step_id"] = step['id']
            return result

    return result


def execute_pipeline(plan: dict, context_summary: str) -> dict:
    """
    Execute all steps in the pipeline DAG in dependency order.
    Returns all results keyed by step_id.
    """
    print(f"\n🚀 Starting pipeline execution: {len(plan['steps'])} steps")
    print(f"   Complexity: {plan['estimated_complexity']}")

    results = {}
    failed_steps = []

    for step in plan['steps']:
        # Check dependencies
        deps_ok = all(
            results.get(dep, {}).get("status") == "success"
            for dep in step.get("depends_on", [])
        )

        if not deps_ok:
            failed_deps = [
                dep for dep in step.get("depends_on", [])
                if results.get(dep, {}).get("status") != "success"
            ]
            print(f"\n  ⏭️  Skipping [{step['id']}]: dependencies failed: {failed_deps}")
            results[step['id']] = {
                "status": "skipped",
                "reason": f"Dependencies failed: {failed_deps}",
                "summary": "Step skipped due to upstream failure"
            }
            failed_steps.append(step['id'])
            continue

        result = execute_step_with_healing(step, context_summary, results)
        results[step['id']] = result

        if result.get("status") != "success":
            failed_steps.append(step['id'])

    # Pipeline summary
    succeeded = sum(1 for r in results.values() if r.get("status") == "success")
    print(f"\n{'='*50}")
    print(f"PIPELINE COMPLETE: {succeeded}/{len(plan['steps'])} steps succeeded")
    if failed_steps:
        print(f"Failed steps: {failed_steps}")
    print(f"{'='*50}")

    return results


if __name__ == "__main__":
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)

    from src.discovery.mcp_server import discover_all_sources
    from src.planner.agent import plan_pipeline, print_plan

    # Run discovery
    context = discover_all_sources(csv_path="examples/retail.csv")

    # Plan the pipeline
    goal = "Fetch the top 5 transaction categories by total amount from PostgreSQL and show the results"
    plan = plan_pipeline(goal, context["summary"])
    print_plan(plan)

    # Execute with self-healing
    results = execute_pipeline(plan, context["summary"])

    # Show results
    print("\nFINAL RESULTS:")
    for step_id, result in results.items():
        status = result.get("status", "unknown")
        summary = result.get("summary", "")
        print(f"  [{step_id}] {status}: {summary}")