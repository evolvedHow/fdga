#!/usr/bin/env python3
"""
fetch_acs_data.py
Pulls ACS 5-year estimates for all 159 Georgia counties and writes:
  data/parquet/dim_acs.parquet

No API key required for small requests.
Run: python scripts/fetch_acs_data.py
"""

import requests
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────
STATE_FIPS = "13"           # Georgia
ACS_YEAR   = "2022"         # Most recent 5-year ACS
BASE_URL   = f"https://api.census.gov/data/{ACS_YEAR}/acs/acs5"
OUT_DIR    = Path(__file__).parent.parent / "data" / "parquet"
OUT_FILE   = OUT_DIR / "dim_acs.parquet"

# ── Variable groups ───────────────────────────────────────────────────────────
# Each entry: (acs_code, output_col, description)
# We fetch in batches of ~40 vars (Census API limit is 50 per request)

BATCH_1 = [
    # Income & poverty
    ("B19013_001E", "median_hh_income",     "Median household income ($)"),
    ("B17001_002E", "pop_in_poverty",        "Population below poverty line"),
    ("B17001_001E", "pop_poverty_universe",  "Poverty universe (total)"),
    # Education
    ("B15003_001E", "pop_edu_universe",      "Education universe 25+"),
    ("B15003_022E", "pop_bachelors",         "Bachelor's degree"),
    ("B15003_023E", "pop_masters",           "Master's degree"),
    ("B15003_024E", "pop_professional",      "Professional degree"),
    ("B15003_025E", "pop_doctorate",         "Doctorate"),
    # Housing
    ("B25003_001E", "housing_total",         "Total occupied housing units"),
    ("B25003_002E", "housing_owner",         "Owner-occupied units"),
    # Broadband
    ("B28002_001E", "internet_universe",     "Internet universe"),
    ("B28002_004E", "broadband_access",      "Has broadband subscription"),
    # Age
    ("B01002_001E", "median_age",            "Median age"),
    # Total population
    ("B01003_001E", "total_pop",             "Total population"),
    # Foreign born
    ("B05002_001E", "nativity_universe",     "Nativity universe"),
    ("B05002_013E", "foreign_born",          "Foreign born"),
    # Race (for context alongside VAP data)
    ("B02001_002E", "pop_white_alone",       "White alone"),
    ("B02001_003E", "pop_black_alone",       "Black alone"),
    ("B02001_005E", "pop_asian_alone",       "Asian alone"),
    ("B03001_003E", "pop_hispanic",          "Hispanic or Latino"),
]

BATCH_2 = [
    # Employment & industry — using B24080 (sex by industry) universe + B08526 (means of transport)
    # Safer: use B23025 for employment status universe, B08301 for commute
    # Industry breakdown via B08526 not available at county — use C24010 instead
    ("C24010_001E", "employed_universe",     "Employed civilian 16+"),
    ("C24010_003E", "emp_mgmt_business",     "Management/business/science/arts"),
    ("C24010_019E", "emp_service",           "Service occupations"),
    ("C24010_033E", "emp_sales_office",      "Sales and office occupations"),
    ("C24010_039E", "emp_natural_resources", "Natural resources/construction/maintenance"),
    ("C24010_045E", "emp_production",        "Production/transportation/material moving"),
    # Commute — B08303 travel time to work
    ("B08303_001E", "commute_universe",      "Commute universe"),
    ("B08303_012E", "commute_60_89min",      "Commute 60-89 min"),
    ("B08303_013E", "commute_90plus_min",    "Commute 90+ min"),
    # Housing cost burden — B25070 gross rent as % of income
    ("B25070_001E", "rent_burden_universe",  "Rent burden universe"),
    ("B25070_010E", "rent_burdened_50pct",   "Paying 50%+ income on rent"),
    # Veteran status — B21001
    ("B21001_001E", "veteran_universe",      "Civilian noninst pop 18+"),
    ("B21001_002E", "veterans",              "Civilian veterans 18+"),
    # Health insurance — B27001 (proxy for economic precarity)
    ("B27001_001E", "health_ins_universe",   "Health insurance universe"),
    ("B27001_005E", "uninsured_male_u19",    "Uninsured male under 19"),
    ("B27001_033E", "uninsured_female_u19",  "Uninsured female under 19"),
    # Median earnings
    ("B20002_001E", "median_earnings",       "Median earnings for workers"),
]

# ── Fetch ─────────────────────────────────────────────────────────────────────
def fetch_batch(variables):
    codes = [v[0] for v in variables]
    params = {
        "get":  "NAME," + ",".join(codes),
        "for":  "county:*",
        "in":   f"state:{STATE_FIPS}",
    }
    r = requests.get(BASE_URL, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    header = data[0]
    rows   = data[1:]
    df = pd.DataFrame(rows, columns=header)
    # Rename ACS codes to friendly names
    rename = {v[0]: v[1] for v in variables}
    df = df.rename(columns=rename)
    return df

def fetch_all():
    print(f"Fetching ACS {ACS_YEAR} 5-year estimates for Georgia counties...")
    df1 = fetch_batch(BATCH_1)
    print(f"  Batch 1: {len(df1)} counties, {len(df1.columns)} columns")
    df2 = fetch_batch(BATCH_2)
    print(f"  Batch 2: {len(df2)} counties, {len(df2.columns)} columns")

    # Merge on state+county FIPS
    df = pd.merge(df1, df2, on=["NAME","state","county"], suffixes=("","_dup"))
    df = df[[c for c in df.columns if not c.endswith("_dup")]]

    # Clean county name: "Appling County, Georgia" → "APPLING"
    df["county"] = df["NAME"].str.replace(r" County, Georgia", "", regex=True).str.upper().str.strip()

    # Rebuild FIPS cleanly from the 3-digit census county suffix columns
    # After merge, census 'county' column (3-digit suffix) may become county_x
    fips_suffix = df["county_x"] if "county_x" in df.columns else df["county"]
    df["fips"] = "13" + fips_suffix.astype(str).str.zfill(3)
    df = df.drop(columns=["county_x", "county_y"], errors="ignore")

    # Convert all numeric columns
    numeric_cols = [c for c in df.columns if c not in ("NAME","county","state","fips","county_x","county_y")]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # ── Derived metrics ───────────────────────────────────────────────────────
    df["pct_poverty"]       = (df["pop_in_poverty"]    / df["pop_poverty_universe"]   * 100).round(1)
    df["pct_college"]       = ((df["pop_bachelors"] + df["pop_masters"] + df["pop_professional"] + df["pop_doctorate"])
                               / df["pop_edu_universe"] * 100).round(1)
    df["pct_owner_occupied"]= (df["housing_owner"]     / df["housing_total"]           * 100).round(1)
    df["pct_broadband"]     = (df["broadband_access"]   / df["internet_universe"]       * 100).round(1)
    df["pct_foreign_born"]  = (df["foreign_born"]       / df["nativity_universe"]       * 100).round(1)
    df["pct_white_collar"]  = (df["emp_mgmt_business"]  / df["employed_universe"]       * 100).round(1)
    df["pct_blue_collar"]   = (df["emp_production"]     / df["employed_universe"]       * 100).round(1)
    df["pct_service"]       = (df["emp_service"]        / df["employed_universe"]       * 100).round(1)
    df["pct_long_commute"]  = ((df["commute_60_89min"]  + df["commute_90plus_min"])
                               / df["commute_universe"] * 100).round(1)
    df["pct_rent_burdened"] = (df["rent_burdened_50pct"]/ df["rent_burden_universe"]   * 100).round(1)
    df["pct_veteran"]       = (df["veterans"]           / df["veteran_universe"]        * 100).round(1)
    df["pct_black"]         = (df["pop_black_alone"]    / df["total_pop"]               * 100).round(1)
    df["pct_hispanic"]      = (df["pop_hispanic"]       / df["total_pop"]               * 100).round(1)
    df["pct_asian"]         = (df["pop_asian_alone"]    / df["total_pop"]               * 100).round(1)
    df["pct_white"]         = (df["pop_white_alone"]    / df["total_pop"]               * 100).round(1)

    df["acs_year"]     = int(ACS_YEAR)
    df["ingested_at"]  = datetime.utcnow().isoformat()

    # ── Output columns ────────────────────────────────────────────────────────
    keep = [
        "county","fips","acs_year",
        # Raw
        "total_pop","median_hh_income","median_age","median_earnings",
        "pop_in_poverty","foreign_born","veterans",
        "broadband_access","housing_owner","housing_total",
        # Derived %
        "pct_poverty","pct_college","pct_owner_occupied",
        "pct_broadband","pct_foreign_born",
        "pct_white_collar","pct_blue_collar","pct_service",
        "pct_long_commute","pct_rent_burdened","pct_veteran",
        "pct_black","pct_hispanic","pct_asian","pct_white",
        "ingested_at",
    ]
    df = df[[c for c in keep if c in df.columns]]
    return df

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = fetch_all()
    print(f"\nFetched {len(df)} counties, {len(df.columns)} columns")

    # Quick validation
    print("\nSample rows:")
    print(df[["county","median_hh_income","pct_college","pct_poverty","pct_broadband"]].head(5).to_string(index=False))

    print("\nDerived metrics range check:")
    for col in ["pct_poverty","pct_college","pct_broadband","pct_blue_collar","pct_long_commute"]:
        if col in df.columns:
            print(f"  {col}: min={df[col].min():.1f}  max={df[col].max():.1f}  mean={df[col].mean():.1f}")

    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), OUT_FILE)
    print(f"\nWrote {OUT_FILE} ({OUT_FILE.stat().st_size/1024:.0f} KB, {len(df)} rows)")

if __name__ == "__main__":
    main()