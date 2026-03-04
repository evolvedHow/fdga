"""
schema.py — Fair Districts GA Analytics Schema
================================================
Star schema designed for multi-dimensional redistricting analysis.

Fact table:
  district_stats — one row per district per map version

Dimension tables:
  dim_maps        — map version metadata (enacted, proposed, remedy)
  dim_chambers    — chamber metadata
  dim_elections   — election results by district
  dim_geometry    — GeoJSON geometry per district per map version

This schema supports queries like:
  - Compare BVAP across all Senate map versions
  - Which districts flipped majority-minority between 2021 and 2024?
  - What's the average partisan lean in majority-Black districts?
  - How did district populations change between cycles?
"""

import pyarrow as pa

# ── Fact table: district_stats ────────────────────────────────────────────────
DISTRICT_STATS_SCHEMA = pa.schema([
    # Keys
    pa.field("district_id",    pa.string(),  nullable=False),  # e.g. "senate_12_enacted_2024"
    pa.field("district_num",   pa.string(),  nullable=False),  # e.g. "12"
    pa.field("chamber",        pa.string(),  nullable=False),  # senate | house | congress
    pa.field("map_version",    pa.string(),  nullable=False),  # enacted_2024 | proposed_dem | etc
    pa.field("map_year",       pa.int16(),   nullable=True),   # 2021, 2024, etc
    pa.field("legal_status",   pa.string(),  nullable=True),   # enacted | proposed | remedy | prior

    # Population
    pa.field("total_pop",      pa.int32(),   nullable=True),
    pa.field("total_vap",      pa.int32(),   nullable=True),   # voting age population

    # Race/ethnicity VAP counts (raw)
    pa.field("white_vap",      pa.int32(),   nullable=True),
    pa.field("black_vap",      pa.int32(),   nullable=True),
    pa.field("hispanic_vap",   pa.int32(),   nullable=True),
    pa.field("asian_vap",      pa.int32(),   nullable=True),
    pa.field("native_vap",     pa.int32(),   nullable=True),
    pa.field("pacific_vap",    pa.int32(),   nullable=True),
    pa.field("multiracial_vap",pa.int32(),   nullable=True),
    pa.field("bipoc_vap",      pa.int32(),   nullable=True),   # all non-white VAP

    # Race/ethnicity VAP percentages (0.0-1.0)
    pa.field("pct_white_vap",  pa.float32(), nullable=True),
    pa.field("pct_black_vap",  pa.float32(), nullable=True),   # BVAP — key VRA metric
    pa.field("pct_hispanic_vap",pa.float32(),nullable=True),   # HVAP
    pa.field("pct_asian_vap",  pa.float32(), nullable=True),   # AVAP
    pa.field("pct_native_vap", pa.float32(), nullable=True),
    pa.field("pct_pacific_vap",pa.float32(), nullable=True),
    pa.field("pct_bipoc_vap",  pa.float32(), nullable=True),   # total minority VAP

    # VRA flags
    pa.field("is_majority_black",    pa.bool_(), nullable=True),  # pct_black_vap > 0.5
    pa.field("is_majority_minority",  pa.bool_(), nullable=True),  # pct_bipoc_vap > 0.5
    pa.field("is_coalition_district", pa.bool_(), nullable=True),  # bipoc > 0.4 and < 0.5

    # Partisan data
    pa.field("dem_pct_avg",    pa.float32(), nullable=True),   # avg dem % last 3 statewide elections
    pa.field("rep_pct_avg",    pa.float32(), nullable=True),
    pa.field("partisan_margin",pa.float32(), nullable=True),   # dem_pct - rep_pct (+ = Dem lean)
    pa.field("partisan_lean",  pa.string(),  nullable=True),   # "Strong D/R", "Lean D/R", "Toss-up"

    # Metadata
    pa.field("source",         pa.string(),  nullable=True),   # rdh | analyst | census
    pa.field("source_file",    pa.string(),  nullable=True),
    pa.field("ingested_at",    pa.timestamp("ms"), nullable=True),
    pa.field("notes",          pa.string(),  nullable=True),
])

# ── Dimension: map versions ───────────────────────────────────────────────────
DIM_MAPS_SCHEMA = pa.schema([
    pa.field("map_version",    pa.string(),  nullable=False),
    pa.field("chamber",        pa.string(),  nullable=False),
    pa.field("label",          pa.string(),  nullable=True),   # "Senate 2024 Enacted"
    pa.field("legal_status",   pa.string(),  nullable=True),   # enacted | proposed | remedy | prior
    pa.field("cycle",          pa.int16(),   nullable=True),   # 2020, 2010
    pa.field("enacted_date",   pa.string(),  nullable=True),
    pa.field("description",    pa.string(),  nullable=True),
    pa.field("geojson_file",   pa.string(),  nullable=True),   # filename in /data/
    pa.field("rdh_dataset_id", pa.string(),  nullable=True),
])

# ── Dimension: election results ───────────────────────────────────────────────
DIM_ELECTIONS_SCHEMA = pa.schema([
    pa.field("district_id",    pa.string(),  nullable=False),
    pa.field("district_num",   pa.string(),  nullable=False),
    pa.field("chamber",        pa.string(),  nullable=False),
    pa.field("map_version",    pa.string(),  nullable=False),
    pa.field("election_year",  pa.int16(),   nullable=False),
    pa.field("office",         pa.string(),  nullable=True),   # governor | senate | president
    pa.field("dem_votes",      pa.int32(),   nullable=True),
    pa.field("rep_votes",      pa.int32(),   nullable=True),
    pa.field("total_votes",    pa.int32(),   nullable=True),
    pa.field("dem_pct",        pa.float32(), nullable=True),
    pa.field("rep_pct",        pa.float32(), nullable=True),
    pa.field("margin",         pa.float32(), nullable=True),   # dem_pct - rep_pct
    pa.field("winner_party",   pa.string(),  nullable=True),
    pa.field("source",         pa.string(),  nullable=True),
])

# ── Dimension: geometry ───────────────────────────────────────────────────────
DIM_GEOMETRY_SCHEMA = pa.schema([
    pa.field("district_id",    pa.string(),  nullable=False),
    pa.field("district_num",   pa.string(),  nullable=False),
    pa.field("chamber",        pa.string(),  nullable=False),
    pa.field("map_version",    pa.string(),  nullable=False),
    pa.field("geometry_wkt",   pa.string(),  nullable=True),   # WKT for DuckDB spatial queries
    pa.field("centroid_lat",   pa.float64(), nullable=True),
    pa.field("centroid_lon",   pa.float64(), nullable=True),
    pa.field("area_sq_mi",     pa.float64(), nullable=True),
    pa.field("perimeter_mi",   pa.float64(), nullable=True),
    pa.field("compactness",    pa.float64(), nullable=True),   # Polsby-Popper score
])

# ── Map version catalog ────────────────────────────────────────────────────────
# Used by both the ingest script and the frontend config
MAP_VERSION_CATALOG = [
    # Senate
    dict(map_version="senate_prior_2014",  chamber="senate",   label="Senate 2014 (Prior)",         legal_status="prior",    cycle=2010, geojson_file="senate14_census20.geojson"),
    dict(map_version="senate_enacted_2021",chamber="senate",   label="Senate 2021 Enacted",          legal_status="enacted",  cycle=2020, geojson_file="senate_enacted_2123_2024update.geojson"),
    dict(map_version="senate_enacted_2024",chamber="senate",   label="Senate 2024 Enacted",          legal_status="enacted",  cycle=2020, geojson_file="senate_enacted_24_2024update.geojson"),
    dict(map_version="senate_proposed_dem",chamber="senate",   label="Senate Proposed (Dem)",        legal_status="proposed", cycle=2020, geojson_file="senate_prop1_dem.geojson"),
    dict(map_version="senate_proposed_rep",chamber="senate",   label="Senate Proposed (Rep)",        legal_status="proposed", cycle=2020, geojson_file="senate_prop2_rep.geojson"),
    dict(map_version="senate_remedy_2",    chamber="senate",   label="Senate Remedy Map 2",          legal_status="remedy",   cycle=2020, geojson_file="senate_remedy_2.geojson"),
    # House
    dict(map_version="house_prior_2015",   chamber="house",    label="House 2015 (Prior)",           legal_status="prior",    cycle=2010, geojson_file="house15_census20.geojson"),
    dict(map_version="house_enacted_2021", chamber="house",    label="House 2021 Enacted",           legal_status="enacted",  cycle=2020, geojson_file="house_enacted_2123_2024update.geojson"),
    dict(map_version="house_enacted_2024", chamber="house",    label="House 2024 Enacted",           legal_status="enacted",  cycle=2020, geojson_file="house_enacted_24_2024update.geojson"),
    dict(map_version="house_proposed_dem", chamber="house",    label="House Proposed (Dem)",         legal_status="proposed", cycle=2020, geojson_file="house_prop1_dem.geojson"),
    dict(map_version="house_proposed_rep", chamber="house",    label="House Proposed (Rep)",         legal_status="proposed", cycle=2020, geojson_file="house_prop2_rep.geojson"),
    dict(map_version="house_remedy_2",     chamber="house",    label="House Remedy Map 2",           legal_status="remedy",   cycle=2020, geojson_file="house_remedy_2.geojson"),
    # Congress
    dict(map_version="congress_prior_2012",chamber="congress", label="Congress 2012 (Prior)",        legal_status="prior",    cycle=2010, geojson_file="congress12_census20.geojson"),
    dict(map_version="congress_enacted_2021",chamber="congress",label="Congress 2021 Enacted",       legal_status="enacted",  cycle=2020, geojson_file="congress21_census20.geojson"),
    dict(map_version="congress_enacted_2023",chamber="congress",label="Congress 2023 Enacted",       legal_status="enacted",  cycle=2020, geojson_file="congress_enacted_2123_2024update.geojson"),
    dict(map_version="congress_enacted_2024",chamber="congress",label="Congress 2024 Enacted",       legal_status="enacted",  cycle=2020, geojson_file="congress_enacted_24_2024update.geojson"),
    dict(map_version="congress_proposed_dem",chamber="congress",label="Congress Proposed (Dem)",     legal_status="proposed", cycle=2020, geojson_file="congress21_p2.geojson"),
    dict(map_version="congress_remedy_2",  chamber="congress", label="Congress Remedy Map 2",        legal_status="remedy",   cycle=2020, geojson_file="congress_remedy_2.geojson"),
]

# ── RDH column name mappings ───────────────────────────────────────────────────
# Maps RDH's column names → our canonical schema names
# RDH uses different prefixes depending on the dataset version
RDH_COLUMN_MAP = {
    # District identifier
    "DISTRICT": "district_num",
    "district": "district_num",

    # Population
    "TOTPOP":   "total_pop",
    "TOTPOP20": "total_pop",
    "VAP":      "total_vap",
    "VAP20":    "total_vap",

    # Black VAP
    "BVAP":     "black_vap",
    "BVAP20":   "black_vap",
    "NH_BVAP":  "black_vap",

    # Hispanic VAP
    "HVAP":     "hispanic_vap",
    "HVAP20":   "hispanic_vap",

    # Asian VAP
    "ASIANVAP": "asian_vap",
    "ASIANVAP20":"asian_vap",
    "NH_ASIANVAP":"asian_vap",

    # Native
    "AMINVAP":  "native_vap",
    "AMINVAP20":"native_vap",

    # Pacific Islander
    "NHPIVAP":  "pacific_vap",
    "NHPIVAP20":"pacific_vap",

    # Multiracial
    "2MOREVAP": "multiracial_vap",

    # White
    "NH_WVAP":  "white_vap",
    "WVAP":     "white_vap",

    # Existing pct fields (0-1 scale)
    "pct_bvp":  "pct_black_vap",
    "pct_hvp":  "pct_hispanic_vap",
    "pct_avp":  "pct_asian_vap",
    "pct_bp_":  "pct_bipoc_vap",
    "partisan": "dem_pct_avg",
}