import os
import sys
import json
from typing import cast
from anthropic import Anthropic
from anthropic.types.text_block import TextBlock
from anthropic.types.thinking_block import ThinkingBlock
from dotenv import load_dotenv

load_dotenv()

client = Anthropic()

PLANNER_SYSTEM_PROMPT = """You are Aether-Flow's Agentic Planner. You receive a data context (schema + stats from multiple sources) and a user goal. Your job is to decompose the goal into a precise, executable DAG (Directed Acyclic Graph) of pipeline steps.

Rules:
- Each step must be atomic and executable as a single Python function
- Steps must be ordered by dependency (no step can run before its dependencies)
- Be specific about which data source each step uses
- Keep steps focused — one responsibility per step
- Always include a final summary/output step

Respond ONLY with valid JSON in this exact format:
{
  "goal": "the original goal",
  "steps": [
    {
      "id": "step_1",
      "task": "short description of what this step does",
      "depends_on": [],
      "source": "postgresql|csv|weather_api|computed",
      "operation": "fetch|transform|join|analyze|visualize|summarize",
      "details": "specific instructions for code generation"
    }
  ],
  "estimated_complexity": "low|medium|high"
}"""


def plan_pipeline(goal: str, context_summary: str) -> dict:
    """
    Use Claude to decompose a goal into an executable DAG.
    Returns structured plan as a dict.
    """
    print(f"\n🧠 Agentic Planner thinking...")
    print(f"   Goal: {goal}")

    prompt = f"""Here is the available data context:

{context_summary}

User goal: {goal}

Decompose this into an executable pipeline DAG. Be specific about column names and table names from the context above."""

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2000,
        system=PLANNER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )

    first_block = response.content[0]
    if first_block.type == "text":
        raw = cast(TextBlock, first_block).text.strip()
    elif first_block.type == "thinking":
        raw = cast(ThinkingBlock, first_block).thinking.strip()
    else:
        raw = ""

    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        plan = json.loads(raw)
        print(f"   ✓ Plan created: {len(plan['steps'])} steps, complexity: {plan['estimated_complexity']}")
        return plan
    except json.JSONDecodeError as e:
        print(f"   ✗ Failed to parse plan: {e}")
        return {"error": str(e), "raw": raw}


def print_plan(plan: dict):
    """Pretty print the pipeline plan."""
    if "error" in plan:
        print(f"Plan error: {plan['error']}")
        return

    print(f"\n{'='*50}")
    print(f"PIPELINE PLAN")
    print(f"{'='*50}")
    print(f"Goal: {plan['goal']}")
    print(f"Complexity: {plan['estimated_complexity']}")
    print(f"Steps: {len(plan['steps'])}")
    print()

    for step in plan['steps']:
        deps = f" (depends on: {', '.join(step['depends_on'])})" if step['depends_on'] else ""
        print(f"  [{step['id']}] {step['task']}")
        print(f"    Source: {step['source']} | Operation: {step['operation']}{deps}")
        print(f"    Details: {step['details']}")
        print()


if __name__ == "__main__":
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)

    from src.discovery.mcp_server import discover_all_sources

    context = discover_all_sources(csv_path="examples/retail.csv")
    
    goal = "Analyze daily transaction volumes from PostgreSQL and correlate with weather temperature to find if spending patterns change on cold vs warm days"
    
    plan = plan_pipeline(goal, context["summary"])
    print_plan(plan)