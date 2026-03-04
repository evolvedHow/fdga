"""
fetch_election_data.py — Multi-State Election Results Processor
===============================================================
Reads CSV/Excel files from data/raw/elections/ and builds two Parquet tables:
  data/parquet/dim_elections.parquet  — results per county per election
  data/parquet/dim_swings.parquet     — swing analysis between election pairs

Configure STATE_FILTER and STATE_FIPS below for your state.
Works with MIT/Harvard Dataverse county files, tonmcg GitHub CSVs,
GA Secretary of State exports, and most other county-level formats.

Usage:
    python scripts/fetch_election_data.py             # process + validate
    python scripts/fetch_election_data.py --build     # process only
    python scripts/fetch_election_data.py --validate  # validate existing parquet
    python scripts/fetch_election_data.py --state NC  # override state at runtime

Install:
    pip install pandas pyarrow duckdb openpyxl
"""

import re
import sys
import argparse
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
from datetime import datetime, timezone

# ══════════════════════════════════════════════════════════
#  STATE CONFIGURATION — change these for a different state
# ══════════════════════════════════════════════════════════

STATE_FILTER = "Georgia"   # Full state name as it appears in the data
STATE_ABBR   = "GA"        # Two-letter abbreviation
STATE_FIPS   = "13"        # Two-digit FIPS prefix (GA=13, NC=37, PA=42, etc.)

# ══════════════════════════════════════════════════════════

BASE_DIR    = Path(__file__).parent.parent
RAW_DIR     = BASE_DIR / "data" / "raw" / "elections"
PARQUET_DIR = BASE_DIR / "data" / "parquet"
RAW_DIR.mkdir(parents=True, exist_ok=True)
PARQUET_DIR.mkdir(parents=True, exist_ok=True)


# ── Office keyword mapping ─────────────────────────────────────────────────────

OFFICE_ALIASES = {
    "president":  "president",
    "pres":       "president",
    "governor":   "governor",
    "gov":        "governor",
    "senate":     "us_senate",
    "sen":        "us_senate",
    "us_senate":  "us_senate",
    "runoff":     "us_senate_runoff",
    "house":      "us_house",
    "lt_gov":     "lt_governor",
    "lt_governor":"lt_governor",
    "ag":         "attorney_general",
    "attorney":   "attorney_general",
    "sos":        "secretary_of_state",
}

OFFICE_KEYWORDS = {
    "president":        ["president"],
    "governor":         ["governor"],
    "us_senate":        ["u.s. senate", "us senate", "united states senate", "senate"],
    "us_senate_runoff": ["senate", "runoff"],
    "us_house":         ["u.s. house", "us house", "representative", "congress"],
    "lt_governor":      ["lieutenant governor", "lt. governor", "lt governor"],
    "attorney_general": ["attorney general"],
    "secretary_of_state": ["secretary of state"],
}

# Known candidate last names → party (fallback when party column is missing/ambiguous)
KNOWN_DEM = {
    "BIDEN", "CLINTON", "OBAMA", "GORE", "KERRY",
    "ABRAMS", "WARNOCK", "OSSOFF", "HARRIS", "CARTER", "LUCAS",
    "COOPER", "BESHEAR", "WHITMER", "PRITZKER",
}
KNOWN_REP = {
    "TRUMP", "ROMNEY", "MCCAIN", "BUSH",
    "KEMP", "PERDUE", "LOEFFLER", "WALKER", "COLLINS", "ISAKSON",
    "DESANTIS", "ABBOTT", "DEWINE", "SUNUNU",
}


# ── Swing pairs — works for any state ─────────────────────────────────────────
# Add/remove pairs here as needed

SWING_PAIRS = [
    ("pres_2016",      "pres_2020",      "Presidential 2016→2020"),
    ("pres_2020",      "pres_2024",      "Presidential 2020→2024"),
    ("pres_2016",      "pres_2024",      "Presidential 2016→2024 (8yr)"),
    ("gov_2018",       "gov_2022",       "Governor 2018→2022"),
    ("gov_2019",       "gov_2023",       "Governor 2019→2023"),
    ("gov_2020",       "gov_2024",       "Governor 2020→2024"),
    ("sen_2018",       "sen_2020",       "Senate 2018→2020"),
    ("sen_2020",       "sen_runoff_2021","Senate 2020→Runoff 2021"),
    ("sen_runoff_2021","sen_2022",       "Senate Runoff 2021→2022"),
    ("sen_2020",       "sen_2022",       "Senate 2020→2022"),
    ("sen_2022",       "sen_2024",       "Senate 2022→2024"),
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def normalize_county(c: str) -> str:
    return (str(c).upper().strip()
            .replace(" COUNTY", "")
            .replace(" PARISH", "")   # Louisiana
            .replace(" BOROUGH", "")  # Alaska
            .replace(".", "")
            .strip())


def normalize_party(party: str, candidate: str = "") -> str:
    p = str(party).upper().strip()
    c = str(candidate).upper().strip()
    if any(x in p for x in ["DEM", "D-", "DEMOCRATIC", "DFL"]): return "DEM"
    if any(x in p for x in ["REP", "R-", "REPUBLICAN", "GOP"]):  return "REP"
    last = c.split()[-1] if c else ""
    if last in KNOWN_DEM: return "DEM"
    if last in KNOWN_REP: return "REP"
    return "OTHER"


def lean_label(margin: float) -> str:
    if margin >  0.20: return "Strong D"
    if margin >  0.05: return "Lean D"
    if margin > -0.05: return "Competitive"
    if margin > -0.20: return "Lean R"
    return "Strong R"


def election_id_from_path(path: Path) -> tuple[str, int, str, str]:
    stem = path.stem.lower()
    year_m = re.search(r"(20\d{2})", stem)
    year = int(year_m.group(1)) if year_m else 0
    office = "unknown"
    for key, val in OFFICE_ALIASES.items():
        if key in stem:
            office = val
            break
    short = {
        "president": "pres", "governor": "gov", "us_senate": "sen",
        "us_senate_runoff": "sen_runoff", "us_house": "house",
        "lt_governor": "lt_gov", "attorney_general": "ag",
        "secretary_of_state": "sos", "unknown": "unk",
    }
    eid   = f"{short.get(office, office)}_{year}"
    label = f"{office.replace('_', ' ').title()} {year}"
    return eid, year, office, label


def find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    cols_lower = {c.lower().strip(): c for c in df.columns}
    for name in candidates:
        if name.lower() in cols_lower:
            return cols_lower[name.lower()]
    return None


def filter_to_state(df: pd.DataFrame) -> pd.DataFrame:
    """Filter dataframe to configured state using any available state column."""
    for col in df.columns:
        cl = col.lower().strip()
        if cl in ("state", "state_name", "state_po", "state_abbr"):
            col_vals = df[col].str.upper().str.strip()
            # Match by full name or abbreviation
            mask = (
                col_vals.eq(STATE_FILTER.upper()) |
                col_vals.eq(STATE_ABBR.upper())
            )
            filtered = df[mask]
            if not filtered.empty:
                return filtered
    # Try FIPS prefix on jurisdiction_fips
    for col in df.columns:
        if "fips" in col.lower():
            mask = df[col].astype(str).str.zfill(5).str.startswith(STATE_FIPS)
            filtered = df[mask]
            if not filtered.empty:
                return filtered
    # No state column found — assume file is already state-specific
    return df


# ── Parse one file ─────────────────────────────────────────────────────────────

def parse_file(path: Path) -> pd.DataFrame:
    print(f"\n  Parsing: {path.name}")

    try:
        if path.suffix.lower() in (".xlsx", ".xls"):
            xl = pd.ExcelFile(path)
            # GA SoS format: has a "Precinct Results" sheet with county-level data
            if "Precinct Results" in xl.sheet_names:
                print(f"    Detected GA SoS multi-sheet format")
                return parse_sos_excel(path, xl)
            df = pd.read_excel(path, dtype=str)
        else:
            for enc in ["utf-8", "latin-1", "cp1252"]:
                try:
                    df = pd.read_csv(path, dtype=str, encoding=enc)
                    break
                except UnicodeDecodeError:
                    continue
    except Exception as e:
        print(f"    ✗ Could not read: {e}")
        return pd.DataFrame()

    df.columns = [c.strip() for c in df.columns]

    # Filter to state
    before = len(df)
    df = filter_to_state(df)
    if df.empty:
        print(f"    ✗ No rows for state '{STATE_FILTER}' / '{STATE_ABBR}'")
        return pd.DataFrame()
    if len(df) < before:
        print(f"    Filtered {before} → {len(df)} rows for {STATE_ABBR}")

    eid, year, office, label = election_id_from_path(path)
    print(f"    Detected: {eid} | {label}")

    # Find columns
    county_col    = find_col(df, ["county_name", "county", "jurisdiction_name", "County", "CTYNAME"])
    party_col     = find_col(df, ["party_detailed", "party_simplified", "party", "Party"])
    candidate_col = find_col(df, ["candidate", "candidate_name", "Candidate"])
    votes_col     = find_col(df, ["candidatevotes", "votes", "total_votes", "Votes", "votes_dem"])
    office_col    = find_col(df, ["office", "Office", "race", "Race", "contest"])

    # Special handling for tonmcg format (pre-aggregated dem/rep columns)
    if find_col(df, ["votes_dem"]) and find_col(df, ["votes_rep"]):
        return parse_preaggregated(df, path, eid, year, office, label, county_col)

    if not county_col:
        print(f"    ✗ Cannot find county column. Columns: {df.columns.tolist()}")
        return pd.DataFrame()
    if not votes_col:
        print(f"    ✗ Cannot find votes column. Columns: {df.columns.tolist()}")
        return pd.DataFrame()

    # Filter to specific office if the file contains multiple
    if office_col and office != "unknown":
        keywords = OFFICE_KEYWORDS.get(office, [])
        if keywords:
            mask = df[office_col].str.lower().str.contains("|".join(keywords), na=False)
            filtered = df[mask]
            if not filtered.empty:
                df = filtered
                print(f"    Filtered to {len(df)} rows for '{office}'")

    # Aggregate by county + party
    rows = []
    for county, cdf in df.groupby(county_col):
        county_norm = normalize_county(str(county))
        if not county_norm or county_norm in ("", "STATE", "TOTAL", "STATEWIDE"):
            continue

        party_votes: dict[str, int] = {}
        for _, row in cdf.iterrows():
            try:
                v = int(float(str(row[votes_col]).replace(",", "").strip()))
            except (ValueError, AttributeError):
                continue
            party = "OTHER"
            if party_col and pd.notna(row.get(party_col)):
                cand = str(row.get(candidate_col, "")) if candidate_col else ""
                party = normalize_party(str(row[party_col]), cand)
            elif candidate_col and pd.notna(row.get(candidate_col)):
                party = normalize_party("", str(row[candidate_col]))
            party_votes[party] = party_votes.get(party, 0) + v

        rows.append(build_row(eid, year, office, label, path.name, county_norm, party_votes))

    result = pd.DataFrame([r for r in rows if r])
    print(f"    ✓ {len(result)} counties parsed")
    return result


def parse_sos_excel(path: Path, xl: "pd.ExcelFile") -> pd.DataFrame:
    """Handle GA Secretary of State Excel exports (Precinct Results sheet = county-level)."""
    eid, year, office, label = election_id_from_path(path)
    print(f"    Detected: {eid} | {label}")

    df = xl.parse("Precinct Results", dtype=str)
    df.columns = [c.strip() for c in df.columns]

    # Expected cols: Precinct, Office Name, Contest ID, Ballot Name, Choice ID, Party, Total
    precinct_col = find_col(df, ["Precinct", "precinct", "County"])
    office_col   = find_col(df, ["Office Name", "office_name", "Office", "office"])
    party_col    = find_col(df, ["Party", "party"])
    votes_col    = find_col(df, ["Total", "total", "Votes", "votes"])

    if not precinct_col or not votes_col:
        print(f"    ✗ GA SoS: missing columns. Found: {df.columns.tolist()}")
        return pd.DataFrame()

    # Filter to target office using filename keywords
    if office_col and office != "unknown":
        keywords = OFFICE_KEYWORDS.get(office, [])
        if keywords:
            mask = df[office_col].str.lower().str.contains("|".join(keywords), na=False)
            filtered = df[mask]
            if not filtered.empty:
                df = filtered
                print(f"    Filtered to {len(df)} rows for '{office}'")

    rows = []
    for county_raw, cdf in df.groupby(precinct_col):
        county_norm = normalize_county(str(county_raw))
        if not county_norm or county_norm in ("", "STATE", "TOTAL", "STATEWIDE"):
            continue

        party_votes: dict[str, int] = {}
        for _, row in cdf.iterrows():
            # Skip "Total Votes" summary rows (no Party value)
            if party_col and (pd.isna(row.get(party_col)) or str(row.get(party_col, "")).strip() == ""):
                continue
            try:
                v = int(float(str(row[votes_col]).replace(",", "").strip()))
            except (ValueError, AttributeError):
                continue
            party = "OTHER"
            if party_col and pd.notna(row.get(party_col)):
                ballot_name = str(row.get(find_col(cdf, ["Ballot Name", "ballot_name", "Candidate", "candidate"]) or "", ""))
                party = normalize_party(str(row[party_col]), ballot_name)
            party_votes[party] = party_votes.get(party, 0) + v

        built = build_row(eid, year, office, label, path.name, county_norm, party_votes)
        if built:
            rows.append(built)

    result = pd.DataFrame(rows)
    print(f"    ✓ {len(result)} counties parsed (GA SoS format)")
    return result



def parse_preaggregated(df, path, eid, year, office, label, county_col) -> pd.DataFrame:
    """Handle tonmcg-style files with votes_dem / votes_rep already split."""
    votes_dem_col = find_col(df, ["votes_dem"])
    votes_rep_col = find_col(df, ["votes_rep", "votes_gop"])
    total_col     = find_col(df, ["total_votes", "votes_total"])

    if not county_col or not votes_dem_col or not votes_rep_col:
        print(f"    ✗ Pre-aggregated format but missing columns")
        return pd.DataFrame()

    rows = []
    for _, row in df.iterrows():
        county_norm = normalize_county(str(row[county_col]))
        if not county_norm or county_norm in ("", "STATE", "TOTAL"):
            continue
        try:
            dem = int(float(str(row[votes_dem_col]).replace(",", "")))
            rep = int(float(str(row[votes_rep_col]).replace(",", "")))
        except (ValueError, AttributeError):
            continue
        other = 0
        if total_col and pd.notna(row.get(total_col)):
            try:
                total = int(float(str(row[total_col]).replace(",", "")))
                other = max(0, total - dem - rep)
            except (ValueError, AttributeError):
                pass
        rows.append(build_row(eid, year, office, label, path.name, county_norm,
                              {"DEM": dem, "REP": rep, "OTHER": other}))

    result = pd.DataFrame([r for r in rows if r])
    print(f"    ✓ {len(result)} counties parsed (pre-aggregated format)")
    return result


def build_row(eid, year, office, label, source_file, county, party_votes) -> dict | None:
    dem   = party_votes.get("DEM", 0)
    rep   = party_votes.get("REP", 0)
    other = party_votes.get("OTHER", 0)
    total = dem + rep + other
    if total == 0:
        return None
    dem_pct = round(dem / total, 4)
    rep_pct = round(rep / total, 4)
    margin  = round(dem_pct - rep_pct, 4)
    return {
        "election_id":   eid,
        "year":          year,
        "office":        office,
        "label":         label,
        "state":         STATE_ABBR,
        "source_file":   source_file,
        "county":        county,
        "dem_votes":     dem,
        "rep_votes":     rep,
        "other_votes":   other,
        "total_votes":   total,
        "dem_pct":       dem_pct,
        "rep_pct":       rep_pct,
        "margin":        margin,
        "winner":        "DEM" if dem > rep else "REP",
        "partisan_lean": lean_label(margin),
        "ingested_at":   datetime.now(timezone.utc),
    }


# ── Swing analysis ─────────────────────────────────────────────────────────────

def build_swings(df: pd.DataFrame) -> pd.DataFrame:
    available = set(df["election_id"].unique())
    rows = []
    for from_id, to_id, label in SWING_PAIRS:
        if from_id not in available or to_id not in available:
            continue
        a = (df[df["election_id"] == from_id][["county", "margin", "year"]]
             .rename(columns={"margin": "m_from", "year": "year_from"}))
        b = (df[df["election_id"] == to_id][["county", "margin", "year"]]
             .rename(columns={"margin": "m_to", "year": "year_to"}))
        m = a.merge(b, on="county", how="inner")
        if m.empty:
            continue
        m["swing"]       = (m["m_to"] - m["m_from"]).round(4)
        m["swing_pp"]    = (m["swing"] * 100).round(2)
        m["swing_label"] = label
        m["from_id"]     = from_id
        m["to_id"]       = to_id
        m["state"]       = STATE_ABBR
        m["swing_dir"]   = m["swing"].apply(
            lambda x: "Toward D" if x > 0.02 else ("Toward R" if x < -0.02 else "Stable")
        )
        rows.append(m[["county", "state", "swing_label", "from_id", "to_id",
                        "year_from", "year_to", "swing", "swing_pp",
                        "swing_dir", "m_from", "m_to"]])
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


# ── Write Parquet ──────────────────────────────────────────────────────────────

def write_parquet(df: pd.DataFrame, path: Path):
    if df.empty:
        print(f"  ⚠  Empty — skipping {path.name}")
        return
    if "ingested_at" in df.columns:
        df["ingested_at"] = pd.to_datetime(df["ingested_at"], utc=True)
    pq.write_table(
        pa.Table.from_pandas(df, preserve_index=False),
        path, compression="snappy", write_statistics=True
    )
    print(f"  ✓ {path.name}: {len(df)} rows ({path.stat().st_size // 1024} KB)")


# ── Main build ─────────────────────────────────────────────────────────────────

def build():
    files = sorted([
        f for f in RAW_DIR.iterdir()
        if f.suffix.lower() in (".csv", ".xlsx", ".xls")
        and not f.name.startswith(".")
    ])

    if not files:
        print(f"\n❌ No CSV/Excel files found in {RAW_DIR}")
        print("   Drop your county election result files there and re-run.")
        sys.exit(1)

    print(f"\n{'='*55}")
    print(f"State: {STATE_FILTER} ({STATE_ABBR})  FIPS prefix: {STATE_FIPS}")
    print(f"Processing {len(files)} file(s) from {RAW_DIR}")
    print(f"{'='*55}")

    parsed = []
    for f in files:
        df = parse_file(f)
        if not df.empty:
            parsed.append(df)

    if not parsed:
        print("\n❌ No data parsed. Check file formats and STATE_FILTER config.")
        sys.exit(1)

    combined = (
        pd.concat(parsed, ignore_index=True)
        .drop_duplicates(subset=["election_id", "county"])
        .sort_values(["year", "office", "county"])
        .reset_index(drop=True)
    )

    print(f"\n  Total: {len(combined)} rows | "
          f"{combined['election_id'].nunique()} elections | "
          f"{combined['county'].nunique()} counties")

    print(f"\nWriting → {PARQUET_DIR}")
    write_parquet(combined, PARQUET_DIR / "dim_elections.parquet")

    swings = build_swings(combined)
    if not swings.empty:
        write_parquet(swings, PARQUET_DIR / "dim_swings.parquet")
    else:
        print("  ℹ  No swing pairs found yet (need matching election pairs)")

    print("\n✅ Done.")


# ── Validate ───────────────────────────────────────────────────────────────────

def validate():
    import duckdb
    conn = duckdb.connect(":memory:")
    ep = PARQUET_DIR / "dim_elections.parquet"
    if not ep.exists():
        print("❌ dim_elections.parquet not found — run --build first")
        return

    print(f"\n{'='*55}\nElection summary — {STATE_ABBR}\n{'='*55}")
    print(conn.execute(f"""
        SELECT year, office, label,
               COUNT(DISTINCT county)                          AS counties,
               SUM(CASE WHEN winner='DEM' THEN 1 ELSE 0 END)  AS dem_counties,
               SUM(CASE WHEN winner='REP' THEN 1 ELSE 0 END)  AS rep_counties,
               ROUND(AVG(margin) * 100, 1)                    AS avg_margin_pp
        FROM read_parquet('{ep}')
        GROUP BY year, office, label, election_id
        ORDER BY year, office
    """).df().to_string(index=False))

    sp = PARQUET_DIR / "dim_swings.parquet"
    if sp.exists():
        pairs = conn.execute(
            f"SELECT DISTINCT swing_label FROM read_parquet('{sp}')"
        ).df()
        print(f"\nSwing pairs: {pairs['swing_label'].tolist()}")
        first = pairs['swing_label'].iloc[0]
        print(f"\nTop swings — {first}:")
        print(conn.execute(f"""
            SELECT county,
                   ROUND(m_from * 100, 1) AS from_pct,
                   ROUND(m_to   * 100, 1) AS to_pct,
                   ROUND(swing  * 100, 1) AS swing_pp,
                   swing_dir
            FROM read_parquet('{sp}')
            WHERE swing_label = '{first}'
            ORDER BY ABS(swing) DESC LIMIT 10
        """).df().to_string(index=False))


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    global STATE_FILTER, STATE_ABBR, STATE_FIPS

    # State FIPS lookup for --state override
    STATE_FIPS_MAP = {
        "AL":"01","AK":"02","AZ":"04","AR":"05","CA":"06","CO":"08","CT":"09",
        "DE":"10","FL":"12","GA":"13","HI":"15","ID":"16","IL":"17","IN":"18",
        "IA":"19","KS":"20","KY":"21","LA":"22","ME":"23","MD":"24","MA":"25",
        "MI":"26","MN":"27","MS":"28","MO":"29","MT":"30","NE":"31","NV":"32",
        "NH":"33","NJ":"34","NM":"35","NY":"36","NC":"37","ND":"38","OH":"39",
        "OK":"40","OR":"41","PA":"42","RI":"44","SC":"45","SD":"46","TN":"47",
        "TX":"48","UT":"49","VT":"50","VA":"51","WA":"53","WV":"54","WI":"55",
        "WY":"56","DC":"11",
    }
    STATE_NAMES = {
        "AL":"Alabama","AK":"Alaska","AZ":"Arizona","AR":"Arkansas","CA":"California",
        "CO":"Colorado","CT":"Connecticut","DE":"Delaware","FL":"Florida","GA":"Georgia",
        "HI":"Hawaii","ID":"Idaho","IL":"Illinois","IN":"Indiana","IA":"Iowa",
        "KS":"Kansas","KY":"Kentucky","LA":"Louisiana","ME":"Maine","MD":"Maryland",
        "MA":"Massachusetts","MI":"Michigan","MN":"Minnesota","MS":"Mississippi",
        "MO":"Missouri","MT":"Montana","NE":"Nebraska","NV":"Nevada","NH":"New Hampshire",
        "NJ":"New Jersey","NM":"New Mexico","NY":"New York","NC":"North Carolina",
        "ND":"North Dakota","OH":"Ohio","OK":"Oklahoma","OR":"Oregon","PA":"Pennsylvania",
        "RI":"Rhode Island","SC":"South Carolina","SD":"South Dakota","TN":"Tennessee",
        "TX":"Texas","UT":"Utah","VT":"Vermont","VA":"Virginia","WA":"Washington",
        "WV":"West Virginia","WI":"Wisconsin","WY":"Wyoming","DC":"District of Columbia",
    }

    p = argparse.ArgumentParser(description="Multi-state election data processor")
    p.add_argument("--build",    action="store_true", help="Process files → Parquet")
    p.add_argument("--validate", action="store_true", help="Validate existing Parquet")
    p.add_argument("--state",    type=str, default=None,
                   help="Two-letter state abbreviation, e.g. --state NC")
    args = p.parse_args()

    if args.state:
        abbr = args.state.upper()
        if abbr not in STATE_FIPS_MAP:
            print(f"❌ Unknown state abbreviation: {abbr}")
            sys.exit(1)
        STATE_ABBR   = abbr
        STATE_FIPS   = STATE_FIPS_MAP[abbr]
        STATE_FILTER = STATE_NAMES[abbr]
        print(f"State override: {STATE_FILTER} ({STATE_ABBR}), FIPS {STATE_FIPS}")

    if args.validate:
        validate()
    elif args.build:
        build()
    else:
        build()
        validate()


if __name__ == "__main__":
    main()