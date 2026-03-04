"""
DuckDB Tool for Fair Districts GA
===================================
Queries Parquet files using the analytics star schema.
Falls back to CSV if Parquet not yet generated.
"""

import os
import duckdb
import pandas as pd
from pathlib import Path
from crewai.tools import BaseTool
from pydantic import BaseModel, Field, model_validator
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


class DuckDBQueryInput(BaseModel):
    sql: Optional[str] = Field(default=None, description="""
A SELECT SQL query against Georgia redistricting data.

── TABLES ────────────────────────────────────────────────────
  district_stats    — main fact table, all chambers combined
  senate_districts  — Senate only
  house_districts   — House only
  congress_districts— Congressional only
  dim_maps          — map version metadata

── KEY COLUMNS ───────────────────────────────────────────────
  district_id       — unique key e.g. 'senate_12_senate_enacted_2024'
  district_num      — district number e.g. '12'
  chamber           — 'senate' | 'house' | 'congress'
  map_version       — see below
  legal_status      — 'enacted' | 'proposed' | 'remedy' | 'prior'
  map_year          — 2021, 2024 etc

── DEMOGRAPHICS (pct_ columns are 0.0-1.0 decimals) ─────────
  pct_black_vap     — BVAP % (key VRA metric)
  pct_hispanic_vap  — HVAP %
  pct_asian_vap     — AVAP %
  pct_bipoc_vap     — all minority VAP %
  black_vap         — BVAP count
  total_pop         — total population
  total_vap         — total voting age population

── VRA FLAGS ─────────────────────────────────────────────────
  is_majority_black     — pct_black_vap > 50%
  is_majority_minority  — pct_bipoc_vap > 50%
  is_coalition_district — 40-50% minority VAP

── PARTISAN ──────────────────────────────────────────────────
  dem_pct_avg       — avg Dem % (0.0-1.0)
  partisan_margin   — dem - rep (positive = Dem lean)
  partisan_lean     — 'Strong D/R' | 'Lean D/R' | 'Toss-up'

── MAP VERSION VALUES ─────────────────────────────────────────
  senate_enacted_2024   senate_enacted_2021   senate_prior_2014
  senate_proposed_dem   senate_proposed_rep   senate_remedy_2
  house_enacted_2024    house_enacted_2021    house_prior_2015
  house_proposed_dem    house_proposed_rep    house_remedy_2
  congress_enacted_2024 congress_enacted_2023 congress_enacted_2021
  congress_proposed_dem congress_remedy_2     congress_prior_2012

── EXAMPLE QUERIES ───────────────────────────────────────────
  -- Districts with >50% BVAP in 2024 Senate map
  {"sql": "SELECT district_num, ROUND(pct_black_vap*100,1) as bvap_pct FROM senate_districts WHERE map_version = 'senate_enacted_2024' AND pct_black_vap > 0.5 ORDER BY pct_black_vap DESC"}

  -- Compare majority-minority districts across map versions
  {"sql": "SELECT map_version, COUNT(*) as mm_districts FROM district_stats WHERE chamber='senate' AND is_majority_minority=true GROUP BY map_version ORDER BY map_version"}

  -- VRA coalition districts
  {"sql": "SELECT district_num, ROUND(pct_black_vap*100,1) as bvap, ROUND(pct_bipoc_vap*100,1) as bipoc FROM senate_districts WHERE map_version='senate_enacted_2024' AND is_coalition_district=true"}
""")
    query:       Optional[str]  = Field(default=None)
    table:       Optional[str]  = Field(default=None)
    filter:      Optional[str]  = Field(default=None)
    conditions:  Optional[str]  = Field(default=None)
    where:       Optional[str]  = Field(default=None)
    columns:     Optional[str]  = Field(default=None)
    map_version: Optional[str]  = Field(default=None)
    chamber:     Optional[str]  = Field(default=None)
    explain:     Optional[bool] = Field(default=False)
    limit:       Optional[int]  = Field(default=None)

    @model_validator(mode="before")
    @classmethod
    def build_sql_from_any_input(cls, values: dict) -> dict:
        # Strip CrewAI metadata
        values = {k: v for k, v in values.items()
                  if k != "metadata" and not (isinstance(v, dict) and "run_id" in v)}

        # Already have proper SQL
        for key in ("sql", "query", "statement", "sql_query", "query_string"):
            val = values.get(key)
            if val and isinstance(val, str) and val.strip().upper().startswith(("SELECT", "WITH")):
                values["sql"] = val.strip()
                return values

        # Build SQL from structured args
        chamber = (values.get("chamber") or "").lower()
        if "house" in chamber:
            table = "house_districts"
        elif "congress" in chamber:
            table = "congress_districts"
        elif "senate" in chamber:
            table = "senate_districts"
        else:
            table = values.get("table", "district_stats")
            if isinstance(table, str):
                t = table.lower()
                if "house" in t:      table = "house_districts"
                elif "congress" in t: table = "congress_districts"
                elif "senate" in t:   table = "senate_districts"
                else:                 table = "district_stats"

        conditions = []
        mv = values.get("map_version")
        if mv:
            conditions.append(f"map_version = '{mv}'")

        for field in ("filter", "where", "conditions"):
            val = values.get(field)
            if val and isinstance(val, str):
                conditions.append(val)

        # Handle pct threshold args
        for col, aliases in {
            "pct_black_vap":    ["pct_black_vap", "pct_bvap", "bvap"],
            "pct_hispanic_vap": ["pct_hispanic_vap", "pct_hvap", "hvap"],
            "pct_asian_vap":    ["pct_asian_vap", "pct_avap", "avap"],
            "pct_bipoc_vap":    ["pct_bipoc_vap", "bipoc"],
        }.items():
            for alias in aliases:
                val = values.get(alias)
                if val is not None and isinstance(val, (int, float)):
                    threshold = val / 100 if val > 1 else val
                    conditions.append(f"{col} > {threshold}")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        cols  = values.get("columns") or "*"
        limit = values.get("limit") or 56

        values["sql"] = f"SELECT {cols} FROM {table} {where_clause} ORDER BY district_num LIMIT {limit}"
        return values

    model_config = {"extra": "allow"}


class DistrictDataTool(BaseTool):
    name: str = "query_district_data"
    description: str = """Query Georgia redistricting data using SQL.

Pass a complete SQL SELECT in the 'sql' field.
Main tables: district_stats | senate_districts | house_districts | congress_districts
Key columns: district_num, chamber, map_version, legal_status, pct_black_vap, pct_hispanic_vap, pct_asian_vap, pct_bipoc_vap, is_majority_black, is_majority_minority, partisan_lean, dem_pct_avg, total_pop, total_vap
pct_* columns are 0.0-1.0 decimals (multiply by 100 for %)
map_version examples: 'senate_enacted_2024', 'house_enacted_2024', 'congress_enacted_2024'

Example: {"sql": "SELECT district_num, ROUND(pct_black_vap*100,1) as bvap_pct FROM senate_districts WHERE map_version='senate_enacted_2024' AND pct_black_vap > 0.5 ORDER BY pct_black_vap DESC"}"""

    args_schema: type[BaseModel] = DuckDBQueryInput
    _data_dir: str = "./data"
    _conn: Optional[duckdb.DuckDBPyConnection] = None

    def model_post_init(self, __context):
        self._data_dir = os.getenv("LOCAL_DATA_DIR", "./data")
        self._setup_connection()

    def _setup_connection(self):
        self._conn = duckdb.connect(":memory:")
        data_dir   = Path(self._data_dir)
        parquet_dir = data_dir / "parquet"

        # Prefer Parquet (analytics schema), fall back to CSV (legacy)
        if parquet_dir.exists() and any(parquet_dir.glob("*.parquet")):
            self._register_parquet(parquet_dir)
        else:
            print("  ⚠ Parquet not found — falling back to CSV")
            print("    Run: python scripts/ingest_to_parquet.py geojson")
            self._register_csv(data_dir)

    def _register_parquet(self, parquet_dir: Path):
        """Register Parquet files as DuckDB views."""
        tables = {
            "district_stats":   parquet_dir / "district_stats.parquet",
            "senate_districts": parquet_dir / "senate_districts.parquet",
            "house_districts":  parquet_dir / "house_districts.parquet",
            "congress_districts":parquet_dir / "congress_districts.parquet",
            "dim_maps":         parquet_dir / "dim_maps.parquet",
        }
        for table_name, path in tables.items():
            if path.exists():
                self._conn.execute(
                    f"CREATE VIEW {table_name} AS SELECT * FROM read_parquet('{path}')"
                )
                print(f"  ✓ Parquet: {table_name}")
            else:
                print(f"  ⚠ Missing parquet: {path.name}")

    def _register_csv(self, data_dir: Path):
        """Legacy CSV fallback — remaps old column names to new schema."""
        # Map old CSV column names to new schema via a SELECT alias
        LEGACY_SELECT = """
            SELECT
                CAST(DISTRICT AS VARCHAR)                    AS district_num,
                chamber,
                map_version,
                legal_status,
                total_pop,
                total_vap,
                pct_bvap                                     AS pct_black_vap,
                pct_hvap                                     AS pct_hispanic_vap,
                pct_avap                                     AS pct_asian_vap,
                pct_bipoc_vap,
                partisan_lean                                AS dem_pct_avg,
                CASE WHEN pct_bvap > 0.5  THEN true ELSE false END AS is_majority_black,
                CASE WHEN pct_bipoc_vap > 0.5 THEN true ELSE false END AS is_majority_minority
            FROM read_csv_auto('{path}')
        """
        csv_tables = {
            "senate_districts":   data_dir / "senate_districts.csv",
            "house_districts":    data_dir / "house_districts.csv",
            "congress_districts": data_dir / "congress_districts.csv",
        }
        all_views = []
        for table_name, csv_path in csv_tables.items():
            if csv_path.exists():
                sql = LEGACY_SELECT.format(path=csv_path)
                self._conn.execute(f"CREATE VIEW {table_name} AS {sql}")
                all_views.append(f"SELECT * FROM {table_name}")
                print(f"  ✓ CSV (legacy): {table_name}")
            else:
                print(f"  ⚠ Missing: {csv_path}")

        if all_views:
            union_sql = " UNION ALL ".join(all_views)
            self._conn.execute(f"CREATE VIEW district_stats AS {union_sql}")

    def _run(self, sql: str = None, query: str = None, explain: bool = False, **kwargs) -> str:
        sql = sql or query
        if not sql:
            return 'ERROR: No SQL. Example: {"sql": "SELECT district_num, ROUND(pct_black_vap*100,1) as bvap_pct FROM senate_districts WHERE map_version=\'senate_enacted_2024\' ORDER BY pct_black_vap DESC"}'

        try:
            if not sql.strip().upper().startswith(("SELECT", "WITH")):
                return "ERROR: Only SELECT queries are allowed."

            result_df = self._conn.execute(sql).df()

            if result_df.empty:
                return (
                    "Query returned no results.\n"
                    "Check map_version — examples: 'senate_enacted_2024', "
                    "'house_enacted_2024', 'congress_enacted_2024'"
                )

            output = f"Query returned {len(result_df)} rows:\n\n"
            output += result_df.to_string(index=False, max_rows=56)

            numeric_cols = result_df.select_dtypes(include='number').columns.tolist()
            if numeric_cols and len(result_df) > 1:
                output += "\n\nSummary:\n"
                output += result_df[numeric_cols].describe().round(3).to_string()

            return output

        except duckdb.Error as e:
            return (
                f"SQL Error: {e}\n"
                f"Valid tables: district_stats, senate_districts, house_districts, congress_districts\n"
                f"map_version examples: 'senate_enacted_2024', 'house_enacted_2024', 'congress_enacted_2024'"
            )
        except Exception as e:
            return f"Error: {e}"


def quick_query(sql: str) -> pd.DataFrame:
    return DistrictDataTool()._conn.execute(sql).df()


def list_available_data() -> dict:
    tool = DistrictDataTool()
    info = {}
    for table in ["senate_districts", "house_districts", "congress_districts"]:
        try:
            count = tool._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            versions = tool._conn.execute(
                f"SELECT DISTINCT map_version FROM {table} ORDER BY map_version"
            ).df()["map_version"].tolist()
            info[table] = {"rows": count, "map_versions": versions}
        except Exception as e:
            info[table] = {"error": str(e)}
    return info


if __name__ == "__main__":
    import json
    print(json.dumps(list_available_data(), indent=2))