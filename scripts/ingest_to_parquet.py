"""
ingest_to_parquet.py — Fair Districts GA Data Pipeline
========================================================
Converts GeoJSON files (from Georgia-Explorer or RDH downloads)
into a clean analytics-ready Parquet star schema.

Usage:
    # Ingest from local GeoJSON files
    python scripts/ingest_to_parquet.py --source geojson --geojson-dir ./data

    # Ingest analyst file from Google Drive / local CSV
    python scripts/ingest_to_parquet.py --source analyst --file path/to/file.csv --map-version senate_enacted_2024 --chamber senate

    # Validate existing parquet files
    python scripts/ingest_to_parquet.py --validate

Dependencies:
    pip install geopandas pyarrow pandas shapely
"""

import os
import sys
import json
import argparse
import hashlib
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.schema import (
    DISTRICT_STATS_SCHEMA,
    DIM_MAPS_SCHEMA,
    DIM_ELECTIONS_SCHEMA,
    DIM_GEOMETRY_SCHEMA,
    MAP_VERSION_CATALOG,
    RDH_COLUMN_MAP,
)


# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent.parent
GEOJSON_DIR = BASE_DIR / "data"
PARQUET_DIR = BASE_DIR / "data" / "parquet"
PARQUET_DIR.mkdir(parents=True, exist_ok=True)


# ── GeoJSON field mappings ─────────────────────────────────────────────────────
# Maps the old GeoJSON property names → canonical schema names
GEOJSON_FIELD_MAP = {
    "DISTRICT":  "district_num",
    "district":  "district_num",
    "pct_bvp":   "pct_black_vap",
    "pct_hvp":   "pct_hispanic_vap",
    "pct_avp":   "pct_asian_vap",
    "pct_bp_":   "pct_bipoc_vap",
    "partisan":  "dem_pct_avg",
    "pop":       "total_pop",
    "TOT_POP":   "total_pop",
    "tvap":      "total_vap",
    "VAP":       "total_vap",
    "BVAP":      "black_vap",
    "HVAP":      "hispanic_vap",
    "ASIANVAP":  "asian_vap",
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_district_id(chamber: str, district_num: str, map_version: str) -> str:
    """Create a stable unique ID for a district row."""
    return f"{chamber}_{district_num}_{map_version}"


def classify_partisan(dem_pct: float | None) -> str | None:
    """Convert a dem percentage (0-1) to a human label."""
    if dem_pct is None:
        return None
    if dem_pct >= 0.60:  return "Strong D"
    if dem_pct >= 0.535: return "Lean D"
    if dem_pct >= 0.465: return "Toss-up"
    if dem_pct >= 0.40:  return "Lean R"
    return "Strong R"


def safe_float(val, scale=1.0) -> float | None:
    """Convert value to float, scaling if needed. Returns None on failure."""
    try:
        f = float(val)
        # If value looks like it's already a percentage (> 1.0), scale down
        if scale == 1.0 and f > 1.0:
            f = f / 100.0
        return round(f * scale, 6)
    except (TypeError, ValueError):
        return None


def safe_int(val) -> int | None:
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


# ── GeoJSON ingestion ──────────────────────────────────────────────────────────

def ingest_geojson(geojson_path: Path, chamber: str, map_version: str, source: str = "geojson") -> pd.DataFrame:
    """Extract features from a GeoJSON file into canonical schema rows."""
    print(f"  Reading: {geojson_path.name}")

    with open(geojson_path) as f:
        geojson = json.load(f)

    features = geojson.get("features", [])
    if not features:
        print(f"    ⚠ No features found in {geojson_path.name}")
        return pd.DataFrame()

    # Find map catalog entry
    catalog_entry = next(
        (m for m in MAP_VERSION_CATALOG if m["map_version"] == map_version),
        {}
    )

    rows = []
    for feature in features:
        props = feature.get("properties", {})
        if not props:
            continue

        # Remap field names
        remapped = {}
        for old_key, val in props.items():
            new_key = GEOJSON_FIELD_MAP.get(old_key, old_key)
            remapped[new_key] = val

        district_num = str(remapped.get("district_num", "")).strip()
        if not district_num:
            continue

        # Extract pct values — handle both 0-1 and 0-100 scales
        pct_bvap = safe_float(remapped.get("pct_black_vap"))
        pct_hvap = safe_float(remapped.get("pct_hispanic_vap"))
        pct_avap = safe_float(remapped.get("pct_asian_vap"))
        pct_bipoc = safe_float(remapped.get("pct_bipoc_vap"))
        dem_pct  = safe_float(remapped.get("dem_pct_avg"))

        # Calculate bipoc if missing
        if pct_bipoc is None and pct_bvap is not None:
            pct_bipoc = pct_bvap  # fallback — imperfect but better than null

        # VRA flags
        is_maj_black    = (pct_bvap > 0.5)  if pct_bvap  is not None else None
        is_maj_minority = (pct_bipoc > 0.5) if pct_bipoc is not None else None
        is_coalition    = (0.4 <= pct_bipoc < 0.5) if pct_bipoc is not None else None

        # Partisan
        rep_pct = (1.0 - dem_pct) if dem_pct is not None else None
        margin  = (dem_pct - rep_pct) if (dem_pct and rep_pct) else None

        row = {
            "district_id":        make_district_id(chamber, district_num, map_version),
            "district_num":       district_num,
            "chamber":            chamber,
            "map_version":        map_version,
            "map_year":           catalog_entry.get("cycle"),
            "legal_status":       catalog_entry.get("legal_status"),

            "total_pop":          safe_int(remapped.get("total_pop")),
            "total_vap":          safe_int(remapped.get("total_vap")),
            "black_vap":          safe_int(remapped.get("black_vap")),
            "hispanic_vap":       safe_int(remapped.get("hispanic_vap")),
            "asian_vap":          safe_int(remapped.get("asian_vap")),
            "native_vap":         safe_int(remapped.get("native_vap")),
            "pacific_vap":        safe_int(remapped.get("pacific_vap")),
            "multiracial_vap":    safe_int(remapped.get("multiracial_vap")),
            "bipoc_vap":          safe_int(remapped.get("bipoc_vap")),
            "white_vap":          safe_int(remapped.get("white_vap")),

            "pct_black_vap":      pct_bvap,
            "pct_hispanic_vap":   pct_hvap,
            "pct_asian_vap":      pct_avap,
            "pct_native_vap":     safe_float(remapped.get("pct_native_vap")),
            "pct_pacific_vap":    safe_float(remapped.get("pct_pacific_vap")),
            "pct_bipoc_vap":      pct_bipoc,
            "pct_white_vap":      safe_float(remapped.get("pct_white_vap")),

            "is_majority_black":     is_maj_black,
            "is_majority_minority":  is_maj_minority,
            "is_coalition_district": is_coalition,

            "dem_pct_avg":        dem_pct,
            "rep_pct_avg":        rep_pct,
            "partisan_margin":    margin,
            "partisan_lean":      classify_partisan(dem_pct),

            "source":             source,
            "source_file":        geojson_path.name,
            "ingested_at":        datetime.now(timezone.utc),
            "notes":              None,
        }
        rows.append(row)

    df = pd.DataFrame(rows)
    print(f"    ✓ {len(df)} districts extracted")
    return df


# ── Analyst CSV/Excel ingestion ────────────────────────────────────────────────

def ingest_analyst_file(
    file_path: Path,
    chamber: str,
    map_version: str,
) -> pd.DataFrame:
    """
    Accept an analyst-provided CSV or Excel file from Google Drive.
    Columns don't need to be perfect — we do fuzzy matching.
    """
    print(f"  Reading analyst file: {file_path.name}")

    if file_path.suffix.lower() in (".xlsx", ".xls"):
        df_raw = pd.read_excel(file_path)
    else:
        df_raw = pd.read_csv(file_path)

    print(f"    Raw columns: {df_raw.columns.tolist()}")

    # Normalize column names: lowercase, strip spaces, remove special chars
    df_raw.columns = [c.strip().lower().replace(" ", "_").replace("%", "pct") for c in df_raw.columns]

    # Fuzzy column matching
    col_aliases = {
        "district_num":     ["district", "dist", "district_number", "dist_num", "district_id"],
        "total_pop":        ["total_pop", "totpop", "population", "pop", "tot_pop"],
        "total_vap":        ["total_vap", "vap", "voting_age_pop", "tot_vap"],
        "black_vap":        ["black_vap", "bvap", "nh_bvap", "blackvap"],
        "hispanic_vap":     ["hispanic_vap", "hvap", "hisp_vap", "latinovap"],
        "asian_vap":        ["asian_vap", "asianvap", "aapi_vap"],
        "pct_black_vap":    ["pct_black_vap", "pct_bvap", "pct_bvp", "bvap_pct", "black_pct", "pct_black"],
        "pct_hispanic_vap": ["pct_hispanic_vap", "pct_hvap", "pct_hvp", "hvap_pct"],
        "pct_asian_vap":    ["pct_asian_vap", "pct_avap", "pct_avp", "avap_pct"],
        "pct_bipoc_vap":    ["pct_bipoc_vap", "pct_bp_", "bipoc_pct", "minority_pct", "pct_minority"],
        "dem_pct_avg":      ["dem_pct_avg", "dem_pct", "partisan", "dem_lean", "democratic_pct"],
    }

    renamed = {}
    for canonical, aliases in col_aliases.items():
        for alias in aliases:
            if alias in df_raw.columns:
                renamed[alias] = canonical
                break

    df_raw = df_raw.rename(columns=renamed)
    print(f"    Mapped columns: {renamed}")

    # Build canonical rows
    rows = []
    catalog_entry = next(
        (m for m in MAP_VERSION_CATALOG if m["map_version"] == map_version), {}
    )

    for _, r in df_raw.iterrows():
        district_num = str(r.get("district_num", "")).strip()
        if not district_num:
            continue

        pct_bvap  = safe_float(r.get("pct_black_vap"))
        pct_hvap  = safe_float(r.get("pct_hispanic_vap"))
        pct_avap  = safe_float(r.get("pct_asian_vap"))
        pct_bipoc = safe_float(r.get("pct_bipoc_vap"))
        dem_pct   = safe_float(r.get("dem_pct_avg"))

        if pct_bipoc is None and pct_bvap is not None:
            pct_bipoc = pct_bvap

        rep_pct = (1.0 - dem_pct) if dem_pct is not None else None
        margin  = (dem_pct - rep_pct) if (dem_pct and rep_pct) else None

        rows.append({
            "district_id":        make_district_id(chamber, district_num, map_version),
            "district_num":       district_num,
            "chamber":            chamber,
            "map_version":        map_version,
            "map_year":           catalog_entry.get("cycle"),
            "legal_status":       catalog_entry.get("legal_status"),
            "total_pop":          safe_int(r.get("total_pop")),
            "total_vap":          safe_int(r.get("total_vap")),
            "black_vap":          safe_int(r.get("black_vap")),
            "hispanic_vap":       safe_int(r.get("hispanic_vap")),
            "asian_vap":          safe_int(r.get("asian_vap")),
            "native_vap":         None,
            "pacific_vap":        None,
            "multiracial_vap":    None,
            "bipoc_vap":          None,
            "white_vap":          None,
            "pct_black_vap":      pct_bvap,
            "pct_hispanic_vap":   pct_hvap,
            "pct_asian_vap":      pct_avap,
            "pct_native_vap":     None,
            "pct_pacific_vap":    None,
            "pct_bipoc_vap":      pct_bipoc,
            "pct_white_vap":      None,
            "is_majority_black":    (pct_bvap > 0.5)  if pct_bvap  else None,
            "is_majority_minority": (pct_bipoc > 0.5) if pct_bipoc else None,
            "is_coalition_district":(0.4 <= pct_bipoc < 0.5) if pct_bipoc else None,
            "dem_pct_avg":        dem_pct,
            "rep_pct_avg":        rep_pct,
            "partisan_margin":    margin,
            "partisan_lean":      classify_partisan(dem_pct),
            "source":             "analyst",
            "source_file":        file_path.name,
            "ingested_at":        datetime.now(timezone.utc),
            "notes":              f"Analyst-provided file: {file_path.name}",
        })

    df = pd.DataFrame(rows)
    print(f"    ✓ {len(df)} districts from analyst file")
    return df


# ── Write Parquet ──────────────────────────────────────────────────────────────

def write_parquet(df: pd.DataFrame, output_path: Path, schema: pa.Schema = None):
    """Write DataFrame to Parquet with compression."""
    if df.empty:
        print(f"    ⚠ Empty DataFrame, skipping {output_path.name}")
        return

    # Ensure datetime columns are proper type
    if "ingested_at" in df.columns:
        df["ingested_at"] = pd.to_datetime(df["ingested_at"], utc=True)

    table = pa.Table.from_pandas(df, schema=schema, safe=False)
    pq.write_table(
        table,
        output_path,
        compression="snappy",       # Fast compression, good ratio
        use_dictionary=True,        # Efficient for repeated strings like map_version
        write_statistics=True,      # Enables DuckDB predicate pushdown
    )
    size_kb = output_path.stat().st_size / 1024
    print(f"    ✓ Written: {output_path.name} ({size_kb:.1f} KB, {len(df)} rows)")


# ── Main pipeline ──────────────────────────────────────────────────────────────

def run_geojson_pipeline(geojson_dir: Path):
    """Convert all GeoJSON files to analytics Parquet."""
    print(f"\n{'='*60}")
    print(f"Ingesting GeoJSON files from: {geojson_dir}")
    print(f"Output: {PARQUET_DIR}")
    print(f"{'='*60}\n")

    all_rows = []

    for catalog_entry in MAP_VERSION_CATALOG:
        geojson_file = geojson_dir / catalog_entry["geojson_file"]
        if not geojson_file.exists():
            print(f"  ⚠ Missing: {catalog_entry['geojson_file']} — skipping")
            continue

        df = ingest_geojson(
            geojson_path=geojson_file,
            chamber=catalog_entry["chamber"],
            map_version=catalog_entry["map_version"],
        )
        if not df.empty:
            all_rows.append(df)

    if not all_rows:
        print("\n❌ No data ingested. Check that GeoJSON files exist in data/")
        return

    # Combine all into one fact table
    fact_df = pd.concat(all_rows, ignore_index=True)
    print(f"\n{'='*60}")
    print(f"Total rows: {len(fact_df)}")
    print(f"Chambers: {fact_df['chamber'].unique().tolist()}")
    print(f"Map versions: {fact_df['map_version'].nunique()}")
    print(f"{'='*60}")

    # Write partitioned by chamber for fast filtering
    for chamber in ["senate", "house", "congress"]:
        chamber_df = fact_df[fact_df["chamber"] == chamber].copy()
        if not chamber_df.empty:
            write_parquet(
                chamber_df,
                PARQUET_DIR / f"{chamber}_districts.parquet",
            )

    # Write combined fact table
    write_parquet(fact_df, PARQUET_DIR / "district_stats.parquet")

    # Write dim_maps
    maps_df = pd.DataFrame(MAP_VERSION_CATALOG)
    maps_df["rdh_dataset_id"] = None
    write_parquet(maps_df, PARQUET_DIR / "dim_maps.parquet")

    print(f"\n✅ Pipeline complete. Parquet files in: {PARQUET_DIR}")
    print("\nNext steps:")
    print("  1. Push data/parquet/ to GitHub")
    print("  2. Update duckdb_tool.py to read from parquet/")
    print("  3. Run: python scripts/validate_parquet.py")


def run_analyst_pipeline(file_path: Path, chamber: str, map_version: str):
    """Ingest a single analyst-provided file and merge into existing Parquet."""
    print(f"\nIngesting analyst file: {file_path}")

    df_new = ingest_analyst_file(file_path, chamber, map_version)
    if df_new.empty:
        print("❌ No data extracted")
        return

    # Load existing parquet for this chamber if it exists
    parquet_path = PARQUET_DIR / f"{chamber}_districts.parquet"
    if parquet_path.exists():
        df_existing = pd.read_parquet(parquet_path)
        # Remove any existing rows for this map_version (replace, don't duplicate)
        df_existing = df_existing[df_existing["map_version"] != map_version]
        df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        print(f"  Merged with existing: {len(df_existing)} existing + {len(df_new)} new = {len(df_combined)} total")
    else:
        df_combined = df_new

    write_parquet(df_combined, parquet_path)

    # Also update combined fact table
    fact_path = PARQUET_DIR / "district_stats.parquet"
    if fact_path.exists():
        df_fact = pd.read_parquet(fact_path)
        df_fact = df_fact[df_fact["map_version"] != map_version]
        df_fact = pd.concat([df_fact, df_new], ignore_index=True)
        write_parquet(df_fact, fact_path)

    print(f"\n✅ Analyst file ingested into {parquet_path.name}")


def validate_parquet():
    """Check parquet files for completeness and data quality."""
    import duckdb
    conn = duckdb.connect(":memory:")

    print("\n" + "="*60)
    print("Validating Parquet files")
    print("="*60)

    for parquet_file in sorted(PARQUET_DIR.glob("*.parquet")):
        print(f"\n{parquet_file.name}:")
        try:
            result = conn.execute(f"""
                SELECT
                    COUNT(*) as rows,
                    COUNT(DISTINCT chamber) as chambers,
                    COUNT(DISTINCT map_version) as map_versions,
                    ROUND(AVG(pct_black_vap) * 100, 1) as avg_bvap_pct,
                    SUM(CASE WHEN is_majority_black THEN 1 ELSE 0 END) as majority_black_districts
                FROM read_parquet('{parquet_file}')
                WHERE chamber IS NOT NULL
            """).df()
            print(result.to_string(index=False))

            # Check for nulls in key columns
            nulls = conn.execute(f"""
                SELECT
                    SUM(CASE WHEN district_num IS NULL THEN 1 ELSE 0 END) as null_district,
                    SUM(CASE WHEN pct_black_vap IS NULL THEN 1 ELSE 0 END) as null_bvap,
                    SUM(CASE WHEN map_version IS NULL THEN 1 ELSE 0 END) as null_map_version
                FROM read_parquet('{parquet_file}')
            """).df()
            print("Null counts:", nulls.to_string(index=False))

        except Exception as e:
            print(f"  ❌ Error: {e}")

    print("\n✅ Validation complete")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Fair Districts GA — Data ingestion pipeline"
    )
    subparsers = parser.add_subparsers(dest="command")

    # GeoJSON pipeline
    geojson_cmd = subparsers.add_parser("geojson", help="Ingest GeoJSON files")
    geojson_cmd.add_argument("--dir", default=str(GEOJSON_DIR), help="GeoJSON directory")

    # Analyst file pipeline
    analyst_cmd = subparsers.add_parser("analyst", help="Ingest analyst CSV/Excel file")
    analyst_cmd.add_argument("--file",        required=True, help="Path to CSV or Excel file")
    analyst_cmd.add_argument("--chamber",     required=True, choices=["senate", "house", "congress"])
    analyst_cmd.add_argument("--map-version", required=True, help="e.g. senate_enacted_2024")

    # Validate
    subparsers.add_parser("validate", help="Validate existing Parquet files")

    args = parser.parse_args()

    if args.command == "geojson":
        run_geojson_pipeline(Path(args.dir))
    elif args.command == "analyst":
        run_analyst_pipeline(Path(args.file), args.chamber, args.map_version)
    elif args.command == "validate":
        validate_parquet()
    else:
        # Default: run full GeoJSON pipeline
        run_geojson_pipeline(GEOJSON_DIR)


if __name__ == "__main__":
    main()