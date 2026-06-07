import os
import json
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash.dash import Dash
from dash import html, dcc
from dash.dependencies import Input, Output, State
from dash._callback_context import callback_context
from dotenv import load_dotenv

load_dotenv()

API_BASE = os.getenv("API_BASE", "http://localhost:8000")


def create_dash_app(server=None, url_base_pathname="/dashboard/"):
    """Create and configure the Dash app."""
    if server:
        app = Dash(
            __name__,
            server=server,
            url_base_pathname=url_base_pathname,
            title="Aether-Flow MLOps Dashboard"
        )
    else:
        app = Dash(__name__, title="Aether-Flow MLOps Dashboard")

    app.layout = html.Div([

        # Header
        html.Div([
            html.H1("⚡ Aether-Flow",
                    style={"margin": "0", "color": "#fff", "fontSize": "28px"}),
            html.P("Self-Healing MLOps Pipeline Orchestrator",
                   style={"margin": "4px 0 0 0", "color": "#a0aec0", "fontSize": "14px"}),
        ], style={
            "background": "#1a202c", "padding": "20px 32px",
            "borderBottom": "1px solid #2d3748"
        }),

        # Main content
        html.Div([

            # Left column
            html.Div([

                # Goal input
                html.Div([
                    html.H3("Run Pipeline",
                            style={"color": "#e2e8f0", "marginBottom": "12px"}),
                    dcc.Textarea(
                        id="goal-input",
                        placeholder="Describe your data goal in plain English...\n\nExample: Analyze daily transaction volumes from PostgreSQL and correlate with weather temperature",
                        style={
                            "width": "100%", "height": "100px",
                            "background": "#2d3748", "color": "#e2e8f0",
                            "border": "1px solid #4a5568", "borderRadius": "8px",
                            "padding": "12px", "fontSize": "14px",
                            "resize": "vertical", "boxSizing": "border-box"
                        }
                    ),
                    html.Button(
                        "▶ Run Pipeline",
                        id="run-btn",
                        style={
                            "marginTop": "12px", "padding": "10px 24px",
                            "background": "#4299e1", "color": "#fff",
                            "border": "none", "borderRadius": "6px",
                            "cursor": "pointer", "fontSize": "14px",
                            "fontWeight": "bold"
                        }
                    ),
                    html.Div(id="run-status",
                             style={"marginTop": "12px", "fontSize": "13px"})
                ], style={
                    "background": "#2d3748", "padding": "20px",
                    "borderRadius": "10px", "marginBottom": "20px"
                }),

                # Phase tracker
                html.Div([
                    html.H3("Pipeline Status",
                            style={"color": "#e2e8f0", "marginBottom": "12px"}),
                    html.Div(id="phase-tracker"),
                    dcc.Interval(id="poll-interval", interval=3000,
                                 n_intervals=0, disabled=True),
                    dcc.Store(id="current-job-id"),
                ], style={
                    "background": "#2d3748", "padding": "20px",
                    "borderRadius": "10px", "marginBottom": "20px"
                }),

                # Example goals
                html.Div([
                    html.H3("Example Goals",
                            style={"color": "#e2e8f0", "marginBottom": "12px"}),
                    html.Div([
                        html.Button(
                            goal[:65] + "..." if len(goal) > 65 else goal,
                            id={"type": "example-btn", "index": i},
                            style={
                                "display": "block", "width": "100%",
                                "marginBottom": "8px", "padding": "8px 12px",
                                "background": "#1a202c", "color": "#a0aec0",
                                "border": "1px solid #4a5568", "borderRadius": "6px",
                                "cursor": "pointer", "fontSize": "12px",
                                "textAlign": "left"
                            }
                        )
                        for i, goal in enumerate([
                            "Fetch the top 5 transaction categories by total amount from PostgreSQL and visualize the results",
                            "Show customer segment distribution by risk tier from PostgreSQL as a pie chart",
                            "Analyze transaction amounts by region from PostgreSQL and show regional breakdown",
                            "Compare retail product category revenue from the CSV dataset and show top performers",
                        ])
                    ])
                ], style={
                    "background": "#2d3748", "padding": "20px",
                    "borderRadius": "10px"
                }),

            ], style={"width": "35%", "paddingRight": "20px"}),

            # Right column
            html.Div([

                html.Div(id="stats-cards", style={"marginBottom": "20px"}),

                html.Div([
                    html.Div([
                        dcc.Graph(id="runs-chart", style={"height": "280px"})
                    ], style={"width": "50%", "paddingRight": "10px"}),
                    html.Div([
                        dcc.Graph(id="repairs-chart", style={"height": "280px"})
                    ], style={"width": "50%"}),
                ], style={"display": "flex", "marginBottom": "20px"}),

                html.Div([
                    html.H3("Recent Pipeline Runs",
                            style={"color": "#e2e8f0", "marginBottom": "12px"}),
                    html.Div(id="runs-table")
                ], style={
                    "background": "#2d3748", "padding": "20px",
                    "borderRadius": "10px"
                }),

                dcc.Interval(id="refresh-interval", interval=15000, n_intervals=0),

            ], style={"width": "65%"}),

        ], style={
            "display": "flex", "padding": "24px",
            "background": "#171923", "minHeight": "calc(100vh - 80px)"
        }),

    ], style={
        "background": "#171923", "fontFamily": "system-ui, sans-serif",
        "minHeight": "100vh"
    })

    # ── Callbacks ────────────────────────────────────────────────────

    @app.callback(
        Output("goal-input", "value"),
        [Input({"type": "example-btn", "index": i}, "n_clicks") for i in range(4)],
        prevent_initial_call=True
    )
    def fill_example(*args):
        goals = [
            "Fetch the top 5 transaction categories by total amount from PostgreSQL and visualize the results",
            "Show customer segment distribution by risk tier from PostgreSQL as a pie chart",
            "Analyze transaction amounts by region from PostgreSQL and show regional breakdown",
            "Compare retail product category revenue from the CSV dataset and show top performers",
        ]
        ctx = callback_context
        if not ctx.triggered:
            return ""
        idx = json.loads(ctx.triggered[0]["prop_id"].split(".")[0])["index"]
        return goals[idx]

    @app.callback(
        Output("run-status", "children"),
        Output("current-job-id", "data"),
        Output("poll-interval", "disabled"),
        Input("run-btn", "n_clicks"),
        State("goal-input", "value"),
        prevent_initial_call=True
    )
    def start_pipeline(n_clicks, goal):
        if not goal or not goal.strip():
            return html.Span("Please enter a goal.",
                             style={"color": "#f6ad55"}), None, True
        try:
            r = requests.post(
                f"{API_BASE}/pipeline/run",
                json={"goal": goal.strip()},
                timeout=10
            )
            data = r.json()
            job_id = data.get("job_id")
            return (
                html.Span(f"Pipeline started: {job_id}",
                          style={"color": "#68d391"}),
                job_id,
                False
            )
        except Exception as e:
            return html.Span(f"Error: {e}",
                             style={"color": "#fc8181"}), None, True

    @app.callback(
        Output("phase-tracker", "children"),
        Output("poll-interval", "disabled", allow_duplicate=True),
        Input("poll-interval", "n_intervals"),
        State("current-job-id", "data"),
        prevent_initial_call=True
    )
    def poll_status(n, job_id):
        if not job_id:
            return html.P("No active pipeline.",
                          style={"color": "#718096"}), True

        try:
            r = requests.get(f"{API_BASE}/pipeline/{job_id}/status", timeout=5)
            data = r.json()
            phase = data.get("phase", "queued")
            status = data.get("status", "unknown")

            phases = ["discovery", "planning", "executing", "auditing", "complete"]

            def phase_badge(p):
                labels = {
                    "discovery": "① Discovery", "planning": "② Planning",
                    "executing": "③ Execution", "auditing": "④ Guardian",
                    "complete": "✅ Complete"
                }
                try:
                    current_idx = phases.index(phase) if phase in phases else -1
                    phase_idx = phases.index(p)
                except ValueError:
                    current_idx = -1
                    phase_idx = 0

                if p == phase and p != "complete":
                    bg, color = "#4299e1", "#fff"
                elif phase_idx < current_idx or phase == "complete":
                    bg, color = "#48bb78", "#fff"
                else:
                    bg, color = "#4a5568", "#a0aec0"

                return html.Span(
                    labels.get(p, p),
                    style={
                        "display": "inline-block", "padding": "4px 10px",
                        "background": bg, "color": color,
                        "borderRadius": "12px", "fontSize": "12px",
                        "marginRight": "6px", "marginBottom": "6px"
                    }
                )

            badges = html.Div([phase_badge(p) for p in phases])
            details = html.Div([
                html.P(f"Job: {job_id}",
                       style={"color": "#718096", "fontSize": "12px",
                              "margin": "8px 0 2px"}),
                html.P(f"Status: {status} | Phase: {phase}",
                       style={"color": "#a0aec0", "fontSize": "12px",
                              "margin": "2px 0"}),
            ])

            result_section = html.Div()
            if status == "complete":
                try:
                    rr = requests.get(
                        f"{API_BASE}/pipeline/{job_id}/result", timeout=5)
                    result = rr.json().get("result", {})
                    deploy = result.get("deploy_approved", False)
                    result_section = html.Div([
                        html.Hr(style={"borderColor": "#4a5568", "margin": "12px 0"}),
                        html.P(
                            f"{'APPROVED' if deploy else 'BLOCKED'} — "
                            f"{result.get('steps_succeeded')}/{result.get('total_steps')} steps | "
                            f"{result.get('charts_passed')}/{result.get('charts_audited')} charts passed",
                            style={
                                "color": "#68d391" if deploy else "#fc8181",
                                "fontSize": "13px"
                            }
                        )
                    ])
                except:
                    pass

            stop_polling = status in ("complete", "failed")
            return html.Div([badges, details, result_section]), stop_polling

        except Exception as e:
            return html.P(f"Poll error: {e}",
                          style={"color": "#fc8181", "fontSize": "12px"}), False

    @app.callback(
        Output("stats-cards", "children"),
        Output("runs-chart", "figure"),
        Output("repairs-chart", "figure"),
        Output("runs-table", "children"),
        Input("refresh-interval", "n_intervals")
    )
    def refresh_telemetry(n):
        try:
            r = requests.get(f"{API_BASE}/telemetry/stats", timeout=5)
            stats = r.json()
        except:
            stats = {"overall": {}, "repair_patterns": [], "recent_runs": []}

        overall = stats.get("overall", {})

        cards_data = [
            ("Total Runs", overall.get("total_runs", 0), "#4299e1"),
            ("Approved", overall.get("approved_runs", 0), "#48bb78"),
            ("Total Repairs", overall.get("total_repairs", 0), "#ed8936"),
            ("Avg Time", f"{overall.get('avg_execution_time', 0):.0f}s", "#9f7aea"),
        ]

        cards = html.Div([
            html.Div([
                html.P(label, style={"color": "#a0aec0", "fontSize": "12px",
                                     "margin": "0"}),
                html.H2(str(value), style={"color": color, "margin": "4px 0 0",
                                           "fontSize": "28px"})
            ], style={
                "background": "#2d3748", "padding": "16px 20px",
                "borderRadius": "10px", "flex": "1",
                "marginRight": "12px" if i < 3 else "0",
                "borderTop": f"3px solid {color}"
            })
            for i, (label, value, color) in enumerate(cards_data)
        ], style={"display": "flex"})

        recent = stats.get("recent_runs", [])
        if recent:
            df_runs = pd.DataFrame(recent)
            fig_runs = px.bar(
                df_runs[::-1],
                x="created_at", y="steps_succeeded",
                color="deploy_approved",
                color_discrete_map={True: "#48bb78", False: "#fc8181"},
                title="Pipeline Runs — Steps Succeeded",
                labels={"created_at": "Run Time", "steps_succeeded": "Steps"}
            )
        else:
            fig_runs = go.Figure()
            fig_runs.update_layout(title="Pipeline Runs — No data yet")

        fig_runs.update_layout(
            paper_bgcolor="#2d3748", plot_bgcolor="#1a202c",
            font_color="#e2e8f0", showlegend=False,
            margin=dict(l=40, r=20, t=40, b=40),
            title_font_size=13
        )

        patterns = stats.get("repair_patterns", [])
        if patterns:
            df_repairs = pd.DataFrame(patterns)
            df_repairs["error_short"] = df_repairs["error_type"].str[:30]
            fig_repairs = px.bar(
                df_repairs,
                x="occurrences", y="error_short",
                orientation="h",
                title="Repair Patterns — Error Types",
                color="repair_rate",
                color_continuous_scale=["#fc8181", "#f6ad55", "#68d391"]
            )
        else:
            fig_repairs = go.Figure()
            fig_repairs.update_layout(title="Repair Patterns — No repairs yet")

        fig_repairs.update_layout(
            paper_bgcolor="#2d3748", plot_bgcolor="#1a202c",
            font_color="#e2e8f0",
            margin=dict(l=40, r=20, t=40, b=40),
            title_font_size=13
        )

        if recent:
            table = html.Table([
                html.Thead(html.Tr([
                    html.Th(h, style={
                        "color": "#a0aec0", "fontSize": "12px",
                        "padding": "8px", "textAlign": "left",
                        "borderBottom": "1px solid #4a5568"
                    })
                    for h in ["Run ID", "Goal", "Steps", "Repairs", "Time", "Status"]
                ])),
                html.Tbody([
                    html.Tr([
                        html.Td(r["run_uuid"][:8],
                                style={"padding": "8px", "fontSize": "12px",
                                       "color": "#a0aec0"}),
                        html.Td(r["goal"][:40] + "...",
                                style={"padding": "8px", "fontSize": "12px",
                                       "color": "#e2e8f0"}),
                        html.Td(f"{r['steps_succeeded']}/{r['total_steps']}",
                                style={"padding": "8px", "fontSize": "12px",
                                       "color": "#68d391"}),
                        html.Td(str(r["total_repairs"]),
                                style={"padding": "8px", "fontSize": "12px",
                                       "color": "#ed8936" if r["total_repairs"] > 0 else "#68d391"}),
                        html.Td(f"{r['execution_time']:.0f}s",
                                style={"padding": "8px", "fontSize": "12px",
                                       "color": "#a0aec0"}),
                        html.Td(
                            "Approved" if r["deploy_approved"] else "Blocked",
                            style={"padding": "8px", "fontSize": "12px",
                                   "color": "#68d391" if r["deploy_approved"] else "#fc8181"}
                        ),
                    ], style={"borderBottom": "1px solid #2d3748"})
                    for r in recent
                ])
            ], style={"width": "100%", "borderCollapse": "collapse"})
        else:
            table = html.P("No runs yet. Start a pipeline above.",
                           style={"color": "#718096", "fontSize": "13px"})

        return cards, fig_runs, fig_repairs, table

    return app


if __name__ == "__main__":
    app = create_dash_app()
    app.run(debug=False, port="8050")