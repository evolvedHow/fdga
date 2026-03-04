"""
Extract GeoJSON to CSV
========================
One-time setup script that reads your existing GeoJSON district files
and creates clean CSVs that DuckDB can query instantly.

Run this whenever you add new district maps:
    python scripts/extract_geojson_to_csv.py

The GeoJSON files have properties like:
  DISTRICT, pct_bvp, pct_hvp, pct_avp, pct_bp_, partisan (from main.js)
We normalize these to consistent names in the output CSVs.
"""

import json
import os
import sys
import pandas as pd
from pathlib import Path

# ── Configuration ─────────────────────────────────────────────────────────────
# Maps each district map file to: (chamber, map_version)
GEOJSON_MAP = {
    # Senate maps
    "senate14_census20.geojson":              ("senate",   "enacted_2014"),
    "senate_enacted_2123_2024update.geojson": ("senate",   "enacted_2021"),
    "senate_enacted_24_2024update.geojson":   ("senate",   "enacted_2024"),
    "senate_prop1_dem.geojson":               ("senate",   "proposed_dem"),
    "senate_prop2_rep.geojson":               ("senate",   "proposed_rep"),
    "senate_remedy_2.geojson":                ("senate",   "remedy_2"),
    # House maps
    "house15_census20.geojson":               ("house",    "enacted_2015"),
    "house_enacted_2123_2024update.geojson":  ("house",    "enacted_2021"),
    "house_enacted_24_2024update.geojson":    ("house",    "enacted_2024"),
    "house_prop1_dem.geojson":                ("house",    "proposed_dem"),
    "house_prop2_rep.geojson":                ("house",    "proposed_rep"),
    "house_remedy_2.geojson":                 ("house",    "remedy_2"),
    # Congress maps
    "congress12_census20.geojson":            ("congress", "enacted_2012"),
    "congress21_census20.geojson":            ("congress", "enacted_2021"),
    "congress21_p2.geojson":                  ("congress", "proposed_dem"),
    "congress_enacted_2123_2024update.geojson": ("congress", "enacted_2023"),
    "congress_enacted_24_2024update.geojson": ("congress", "enacted_2024"),
    "congress_remedy_2.geojson":              ("congress", "remedy_2"),
}

# Column name mapping from GeoJSON property names → standardized CSV names
# Update this if your GeoJSON has different property names
COLUMN_REMAP = {
    "DISTRICT":  "DISTRICT",
    "District":  "DISTRICT",
    "district":  "DISTRICT",
    "NAME":      "name",
    "pct_bvp":   "pct_bvap",     # Black VAP % (0.0-1.0)
    "pct_hvp":   "pct_hvap",     # Hispanic VAP %
    "pct_avp":   "pct_avap",     # Asian VAP %
    "pct_bp_":   "pct_bipoc_vap",# BIPOC VAP %
    "partisan":  "partisan_lean",
    "BVAP":      "bvap",         # Raw count
    "HVAP":      "hvap",
    "AVAP":      "avap",
    "TOT_POP":   "total_pop",
    "VAP":       "total_vap",
}


def extract_features_to_df(geojson_path: Path, chamber: str, map_version: str) -> pd.DataFrame:
    """Extract features from one GeoJSON file into a DataFrame."""
    print(f"  Reading: {geojson_path.name}")

    with open(geojson_path, 'r') as f:
        geojson = json.load(f)

    if "features" not in geojson:
        print(f"    ⚠ No 'features' key found — skipping")
        return pd.DataFrame()

    rows = []
    for feature in geojson["features"]:
        props = feature.get("properties", {})
        if props:
            rows.append(props)

    if not rows:
        print(f"    ⚠ No properties found — skipping")
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Rename columns to standardized names
    rename_map = {old: new for old, new in COLUMN_REMAP.items() if old in df.columns}
    df = df.rename(columns=rename_map)

    # Add metadata columns
    df["chamber"] = chamber
    df["map_version"] = map_version

    # Ensure DISTRICT is a string (some files store as int)
    if "DISTRICT" in df.columns:
        df["DISTRICT"] = df["DISTRICT"].astype(str).str.strip()

    # Make sure pct columns are float
    for col in ["pct_bvap", "pct_hvap", "pct_avap", "pct_bipoc_vap", "partisan_lean"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    print(f"    ✓ {len(df)} districts, columns: {df.columns.tolist()}")
    return df


def main():
    # Resolve paths
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent
    data_dir = repo_root / "fdga/data"
    
    # Look for GeoJSON files — check both local data/ and parent project
    geojson_dirs = [
        data_dir,
        repo_root.parent / "Georgia-Explorer" / "data",  # if repos are siblings
        Path(os.getenv("GEOJSON_SOURCE_DIR", str(data_dir))),
    ]

    output_dir = data_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    samples_dir = data_dir / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)

    # Accumulate by chamber
    chamber_dfs = {"senate": [], "house": [], "congress": []}
    found_any = False

    for geojson_dir in geojson_dirs:
        if not geojson_dir.exists():
            continue
        print(f"\nLooking in: {geojson_dir}")

        for filename, (chamber, map_version) in GEOJSON_MAP.items():
            geojson_path = geojson_dir / filename
            if geojson_path.exists():
                found_any = True
                df = extract_features_to_df(geojson_path, chamber, map_version)
                if not df.empty:
                    chamber_dfs[chamber].append(df)

    if not found_any:
        print("""
⚠  No GeoJSON files found!

Options:
1. Copy your GeoJSON files to: data/
   (from the Georgia-Explorer repo's data/ folder)

2. Set GEOJSON_SOURCE_DIR in your .env to point to the data/ folder

3. Run the sample data generator instead:
   python scripts/generate_sample_data.py
""")
        sys.exit(1)

    # Write combined CSVs per chamber
    print("\nWriting CSVs...")
    for chamber, dfs in chamber_dfs.items():
        if not dfs:
            print(f"  ⚠ No data for {chamber}")
            continue

        combined = pd.concat(dfs, ignore_index=True)
        output_path = output_dir / f"{chamber}_districts.csv"
        combined.to_csv(output_path, index=False)
        print(f"  ✓ {output_path.name}: {len(combined)} rows, "
              f"{combined['map_version'].nunique()} map versions")

        # Write a small sample file (first 20 rows) for testing
        sample_path = samples_dir / f"{chamber}_sample.csv"
        combined.head(20).to_csv(sample_path, index=False)
        print(f"    Sample: {sample_path.name}")

    print("\n✅ Done! Data files ready for DuckDB queries.")
    print(f"   Location: {output_dir.absolute()}")


if __name__ == "__main__":
    main()
