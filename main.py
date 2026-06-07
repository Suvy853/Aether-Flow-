import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

from src.discovery.mcp_server import discover_all_sources
from src.planner.agent import plan_pipeline, print_plan
from src.execution.executor import execute_pipeline
from src.guardian.auditor import audit_pipeline_outputs, print_guardian_report
from src.execution.telemetry import get_pipeline_stats


BANNER = """
╔═══════════════════════════════════════════════════════════╗
║           AETHER-FLOW  —  Self-Healing MLOps              ║
║     Discover → Plan → Execute → Heal → Audit → Deploy     ║
╚═══════════════════════════════════════════════════════════╝
"""

EXAMPLE_GOALS = [
    "Fetch the top 5 transaction categories by total amount from PostgreSQL and visualize the results",
    "Analyze daily transaction volumes from PostgreSQL and correlate with weather temperature",
    "Show customer segment distribution by risk tier from PostgreSQL as a pie chart",
    "Compare retail product category revenue from the CSV dataset and show top performers",
    "Analyze transaction amounts by region from PostgreSQL branches and visualize by geography",
]


def clean_outputs(keep_last: int = 5):
    """Keep outputs folder clean — retain only the most recent charts."""
    outputs_dir = Path("outputs")
    outputs_dir.mkdir(exist_ok=True)

    charts = sorted(
        outputs_dir.glob("*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )

    for old_chart in charts[keep_last:]:
        old_chart.unlink()


def run_pipeline(goal: str, csv_path: Optional[str] = None, verbose: bool = True) -> dict:
    """
    Run the full Aether-Flow pipeline end-to-end.

    Phase 1: Discovery
    Phase 2: Planning
    Phase 3: Self-Healing Execution
    Phase 4: Guardian Audit

    Returns the full pipeline report.
    """
    print(BANNER)
    start_time = datetime.now()
    print(f"Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Goal: {goal}\n")

    # Clean old outputs
    clean_outputs()

    # ── Phase 1: Discovery ──────────────────────────────────────
    print("━" * 60)
    print("PHASE 1 — DISCOVERY HUB")
    print("━" * 60)
    context = discover_all_sources(csv_path=csv_path or "examples/retail.csv")

    # ── Phase 2: Planning ───────────────────────────────────────
    print("\n" + "━" * 60)
    print("PHASE 2 — AGENTIC PLANNER")
    print("━" * 60)
    plan = plan_pipeline(goal, context["summary"])

    if "error" in plan:
        print(f"✗ Planning failed: {plan['error']}")
        return {"status": "failed", "phase": "planning", "error": plan["error"]}

    if verbose:
        print_plan(plan)

    # ── Phase 3: Self-Healing Execution ─────────────────────────
    print("\n" + "━" * 60)
    print("PHASE 3 — SELF-HEALING EXECUTION")
    print("━" * 60)
    results, run_uuid = execute_pipeline(plan, context["summary"])

    # ── Phase 4: Guardian Audit ─────────────────────────────────
    print("\n" + "━" * 60)
    print("PHASE 4 — MULTIMODAL GUARDIAN")
    print("━" * 60)
    report = audit_pipeline_outputs(results, plan, goal, run_uuid)

    if verbose:
        print_guardian_report(report)

    # ── Final Summary ────────────────────────────────────────────
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    succeeded = sum(1 for r in results.values() if r.get("status") == "success")
    total_steps = len(plan["steps"])

    print("\n" + "═" * 60)
    print("AETHER-FLOW COMPLETE")
    print("═" * 60)
    print(f"  Run ID:       {run_uuid[:8]}")
    print(f"  Duration:     {duration:.1f}s")
    print(f"  Steps:        {succeeded}/{total_steps} succeeded")
    print(f"  Repairs:      {sum(r.get('repairs_triggered', 0) for r in results.values())}")
    print(f"  Charts:       {report['total_charts']} audited, {report['passed']} passed")
    print(f"  Deployment:   {'✅ APPROVED' if report['deploy_approved'] else '❌ BLOCKED'}")
    print("═" * 60)

    # MLOps stats
    stats = get_pipeline_stats()
    overall = stats.get("overall", {})
    print(f"\n📊 MLOps History:")
    print(f"  Total runs logged:    {overall.get('total_runs', 0)}")
    print(f"  Total repairs logged: {overall.get('total_repairs', 0)}")
    print(f"  Avg execution time:   {overall.get('avg_execution_time', 0):.1f}s")
    print(f"  Approved runs:        {overall.get('approved_runs', 0)}")

    if stats.get("repair_patterns"):
        print(f"\n🔧 Top repair patterns:")
        for p in stats["repair_patterns"][:3]:
            print(f"  {p['error_type'][:60]}: {p['occurrences']} occurrences, {p['repair_rate']}% repaired")

    return {
        "status": "complete",
        "run_uuid": run_uuid,
        "goal": goal,
        "steps_succeeded": succeeded,
        "total_steps": total_steps,
        "deploy_approved": report["deploy_approved"],
        "duration_seconds": duration,
        "report": report
    }


def interactive_mode():
    """Run Aether-Flow in interactive mode — user types goals."""
    print(BANNER)
    print("Interactive mode. Type a goal or choose an example.\n")
    print("Example goals:")
    for i, goal in enumerate(EXAMPLE_GOALS, 1):
        print(f"  {i}. {goal}")

    print("\nOptions:")
    print("  Enter a number (1-5) to use an example goal")
    print("  Type your own goal")
    print("  Type 'stats' to view MLOps telemetry")
    print("  Type 'quit' to exit\n")

    while True:
        try:
            user_input = input("Aether-Flow > ").strip()

            if not user_input:
                continue

            if user_input.lower() == "quit":
                print("Goodbye.")
                break

            if user_input.lower() == "stats":
                stats = get_pipeline_stats()
                print(f"\nMLOps Telemetry:")
                print(f"  Total runs: {stats['overall'].get('total_runs', 0)}")
                print(f"  Total repairs: {stats['overall'].get('total_repairs', 0)}")
                print(f"  Avg execution time: {stats['overall'].get('avg_execution_time', 0):.1f}s")
                print(f"  Approved runs: {stats['overall'].get('approved_runs', 0)}\n")
                continue

            # Check if user entered a number
            if user_input.isdigit():
                idx = int(user_input) - 1
                if 0 <= idx < len(EXAMPLE_GOALS):
                    goal = EXAMPLE_GOALS[idx]
                    print(f"\nUsing: {goal}\n")
                else:
                    print("Invalid number. Try again.")
                    continue
            else:
                goal = user_input

            run_pipeline(goal)
            print("\n" + "-" * 60 + "\n")

        except KeyboardInterrupt:
            print("\nInterrupted. Goodbye.")
            break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Aether-Flow — Self-Healing MLOps Pipeline")
    parser.add_argument("--goal", type=str, help="Pipeline goal in plain English")
    parser.add_argument("--csv", type=str, default="examples/retail.csv", help="Path to CSV file")
    parser.add_argument("--interactive", action="store_true", help="Run in interactive mode")
    parser.add_argument("--stats", action="store_true", help="Show MLOps telemetry stats")

    args = parser.parse_args()

    if args.stats:
        stats = get_pipeline_stats()
        print(json.dumps(stats, indent=2))

    elif args.interactive:
        interactive_mode()

    elif args.goal:
        result = run_pipeline(args.goal, csv_path=args.csv)
        sys.exit(0 if result.get("deploy_approved") else 1)

    else:
        # Default: run with a demo goal
        goal = EXAMPLE_GOALS[0]
        run_pipeline(goal)