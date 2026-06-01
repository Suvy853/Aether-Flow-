import os
import json
import requests
import pandas as pd
import psycopg
from dotenv import load_dotenv
from typing import Any, Optional

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# ─── PostgreSQL probe ───────────────────────────────────────────────

def probe_postgres() -> dict[str, Any]:
    """Extract schema + stats from Railway PostgreSQL without loading raw data."""
    metadata: dict[str, Any] = {"source": "postgresql", "tables": []}
    
    try:
        with psycopg.connect(DATABASE_URL) as conn:  # type: ignore[arg-type]
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public'
                    ORDER BY table_name;
                """)
                tables = [row[0] for row in cur.fetchall()]
                
                for table in tables:
                    table_info = {"name": table, "columns": [], "row_count": 0}
                    
                    cur.execute("""
                        SELECT column_name, data_type, is_nullable
                        FROM information_schema.columns
                        WHERE table_name = %s AND table_schema = 'public'
                        ORDER BY ordinal_position;
                    """, (table,))
                    table_info["columns"] = [
                        {"name": r[0], "type": r[1], "nullable": r[2]}
                        for r in cur.fetchall()
                    ]
                    
                    cur.execute(f"SELECT COUNT(*) FROM {table};")  # type: ignore[arg-type]
                    table_info["row_count"] = cur.fetchone()[0]  # type: ignore[index]
                    
                    cur.execute(f"SELECT * FROM {table} LIMIT 3;")  # type: ignore[arg-type]
                    cols = [desc[0] for desc in cur.description]  # type: ignore[union-attr]
                    rows = cur.fetchall()
                    table_info["sample"] = [dict(zip(cols, row)) for row in rows]
                    
                    metadata["tables"].append(table_info)
                    
        metadata["status"] = "success"
        metadata["table_count"] = len(metadata["tables"])
        
    except Exception as e:
        metadata["status"] = "error"
        metadata["error"] = str(e)
    
    return metadata


# ─── CSV probe ─────────────────────────────────────────────────────

def probe_csv(filepath: str) -> dict[str, Any]:
    """Extract schema + stats from a CSV file without loading all rows."""
    metadata: dict[str, Any] = {"source": "csv", "filepath": filepath}
    
    try:
        df = pd.read_csv(filepath, nrows=100)
        full_df = pd.read_csv(filepath)
        
        metadata["columns"] = []
        for col in full_df.columns:
            col_info = {
                "name": col,
                "dtype": str(full_df[col].dtype),
                "null_count": int(full_df[col].isnull().sum()),
                "unique_count": int(full_df[col].nunique()),
            }
            if full_df[col].dtype == object:
                col_info["sample_values"] = full_df[col].dropna().unique()[:5].tolist()
            elif pd.api.types.is_numeric_dtype(full_df[col]):
                non_null = full_df[col].dropna()
                if len(non_null) > 0:
                    col_info["min"] = float(non_null.min())
                    col_info["max"] = float(non_null.max())
                    col_info["mean"] = round(float(non_null.mean()), 2)
            metadata["columns"].append(col_info)
        
        metadata["row_count"] = len(full_df)
        metadata["sample"] = df.head(3).to_dict(orient="records")
        metadata["status"] = "success"
        
    except Exception as e:
        metadata["status"] = "error"
        metadata["error"] = str(e)
    
    return metadata


# ─── Weather API probe ─────────────────────────────────────────────

def probe_weather_api() -> dict[str, Any]:
    """Extract schema from Open-Meteo API (free, no key required)."""
    metadata: dict[str, Any] = {"source": "weather_api", "provider": "Open-Meteo"}
    
    try:
        url = (
            "https://api.open-meteo.com/v1/forecast"
            "?latitude=42.36&longitude=-71.06"
            "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,windspeed_10m_max"
            "&timezone=America/New_York&past_days=7&forecast_days=1"
        )
        response = requests.get(url, timeout=10)
        data = response.json()
        
        metadata["endpoint"] = url
        metadata["available_fields"] = {
            "daily": list(data.get("daily", {}).keys()),
        }
        metadata["sample"] = {
            "daily": {k: v[:3] for k, v in data.get("daily", {}).items()}
        }
        metadata["timezone"] = data.get("timezone")
        metadata["status"] = "success"
        
    except Exception as e:
        metadata["status"] = "error"
        metadata["error"] = str(e)
    
    return metadata


# ─── Unified discovery ─────────────────────────────────────────────

def discover_all_sources(csv_path: Optional[str] = None) -> dict[str, Any]:
    """
    Run discovery across all 3 data sources.
    Returns a unified metadata context for the agent.
    """
    print("🔍 Aether-Flow Discovery Hub starting...")
    
    context = {
        "sources": [],
        "summary": ""
    }
    
    print("  → Probing PostgreSQL...")
    pg_meta = probe_postgres()
    context["sources"].append(pg_meta)
    if pg_meta["status"] == "success":
        print(f"     ✓ Found {pg_meta['table_count']} tables")
    else:
        print(f"     ✗ Error: {pg_meta['error']}")
    
    if csv_path:
        print(f"  → Probing CSV: {csv_path}")
        csv_meta = probe_csv(csv_path)
        context["sources"].append(csv_meta)
        if csv_meta["status"] == "success":
            print(f"     ✓ Found {csv_meta['row_count']} rows, {len(csv_meta['columns'])} columns")
        else:
            print(f"     ✗ Error: {csv_meta['error']}")
    
    print("  → Probing Weather API...")
    weather_meta = probe_weather_api()
    context["sources"].append(weather_meta)
    if weather_meta["status"] == "success":
        print(f"     ✓ Fields: {weather_meta['available_fields']['daily']}")
    else:
        print(f"     ✗ Error: {weather_meta['error']}")
    
    context["summary"] = build_context_summary(context["sources"])
    print("\n✅ Discovery complete.")
    
    return context


def build_context_summary(sources: list) -> str:
    """
    Compress metadata into a token-efficient summary string
    that Claude can reason over without being overwhelmed.
    """
    lines = ["=== AETHER-FLOW DATA SOURCE CONTEXT ===\n"]
    
    for source in sources:
        if source["status"] != "success":
            lines.append(f"[{source['source'].upper()}] ERROR: {source.get('error')}\n")
            continue
        
        if source["source"] == "postgresql":
            lines.append(f"[POSTGRESQL] {source['table_count']} tables:")
            for t in source["tables"]:
                cols = ", ".join([f"{c['name']}({c['type'][:8]})" for c in t["columns"][:6]])
                lines.append(f"  - {t['name']}: {t['row_count']:,} rows | cols: {cols}")
            lines.append("")
        
        elif source["source"] == "csv":
            lines.append(f"[CSV] {source['filepath']} — {source['row_count']:,} rows:")
            for c in source["columns"][:8]:
                lines.append(f"  - {c['name']} ({c['dtype']})")
            lines.append("")
        
        elif source["source"] == "weather_api":
            fields = source["available_fields"]["daily"]
            lines.append(f"[WEATHER API] Open-Meteo daily fields:")
            lines.append(f"  - {', '.join(fields)}")
            lines.append("")
    
    return "\n".join(lines)


# ─── Quick test ────────────────────────────────────────────────────

if __name__ == "__main__":
    context = discover_all_sources(csv_path="examples/retail.csv")
    print("\n" + "="*50)
    print("CONTEXT SUMMARY (what Claude will see):")
    print("="*50)
    print(context["summary"])