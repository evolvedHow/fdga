# Fair Districts GA — Analytics Dashboard

## Overview

The analytics dashboard (`/frontend/ui_elections.html`) is a real-data election analysis tool layered on top of the main redistricting map. It shows county-level election results, swing analysis, and partisan trends for Georgia using data you download and process locally.

It is served by FastAPI at `http://localhost:8000/frontend/ui_elections.html` and is accessible from the main map via the **Analytics** button in the topbar.

---

## Architecture

```
User browser
    |
    | HTTP
    v
FastAPI (main.py)
    |-- GET /                        → serves index.html (main map)
    |-- GET /frontend/ui_elections.html → serves analytics dashboard (token injected)
    |-- GET /api/elections           → all county results from parquet
    |-- GET /api/elections/summary   → statewide totals per election
    |-- GET /api/swings              → swing analysis between election pairs
    |-- GET /api/swings/pairs        → list of available swing pairs
    |
    |-- /data/parquet/
    |       dim_elections.parquet    → built by fetch_election_data.py
    |       dim_swings.parquet       → built by fetch_election_data.py
    |
    |-- /data/raw/elections/
            *.csv / *.xlsx           → source files you download manually
```

---

## Data Pipeline

### Step 1 — Download election data

**Presidential results (all 3 years, direct download, no login):**

```
https://raw.githubusercontent.com/tonmcg/US_County_Level_Election_Results_08-24/master/2016_US_County_Level_Presidential_Results.csv
https://raw.githubusercontent.com/tonmcg/US_County_Level_Election_Results_08-24/master/2020_US_County_Level_Presidential_Results.csv
https://raw.githubusercontent.com/tonmcg/US_County_Level_Election_Results_08-24/master/2024_US_County_Level_Presidential_Results.csv
```

**GA Secretary of State results (Senate, Governor, Runoff):**

Go to each URL → click **Download Reports** → **County Summary** → download Excel:

| File to save as | URL |
|---|---|
| `2018_general_governor.xlsx` | https://results.sos.ga.gov/results/public/georgia/elections/2018NovGen |
| `2020_general_senate.xlsx` | https://results.sos.ga.gov/results/public/georgia/elections/2020NovGen |
| `2021_runoff_senate.xlsx` | https://results.sos.ga.gov/results/public/georgia/elections/2021JanRunoff |
| `2022_general_governor.xlsx` | https://results.sos.ga.gov/results/public/georgia/elections/2022NovGen |
| `2022_general_senate.xlsx` | https://results.sos.ga.gov/results/public/georgia/elections/2022NovGen |
| `2024_general_senate.xlsx` | https://results.sos.ga.gov/results/public/georgia/elections/2024NovGen |

### Step 2 — Place files

Drop all files into:
```
data/raw/elections/
```

Naming convention (the script auto-detects office and year from filename):
```
2016_general_president.csv
2018_general_governor.xlsx
2020_general_president.csv
2020_general_senate.xlsx
2021_runoff_senate.xlsx
2022_general_governor.xlsx
2022_general_senate.xlsx
2024_general_president.csv
2024_general_senate.xlsx
```

### Step 3 — Run the pipeline

```bash
cd ~/codebox/fdga
python scripts/fetch_election_data.py
```

This produces:
- `data/parquet/dim_elections.parquet` — county results per election (477+ rows)
- `data/parquet/dim_swings.parquet` — swing analysis between paired elections

### Step 4 — Restart the server

```bash
uvicorn main:app --reload --port 8000
```

---

## Supported File Formats

| Format | Detection | Example source |
|---|---|---|
| tonmcg pre-aggregated | `votes_dem` + `votes_gop` columns | tonmcg GitHub CSVs |
| GA SoS Excel | `Precinct Results` sheet present | GA Secretary of State |
| MIT/Harvard Dataverse | `state_name` + `candidatevotes` columns | countypres_2000_2024.csv |

---

## API Endpoints

All endpoints are served by FastAPI at `localhost:8000`.

### `GET /api/elections`
Returns all county-level results across all loaded elections.

```json
[
  {
    "election_id": "pres_2024",
    "year": 2024,
    "office": "president",
    "label": "President 2024",
    "county": "FULTON",
    "dem_votes": 297091,
    "rep_votes": 74617,
    "total_votes": 375482,
    "dem_pct": 79.1,
    "rep_pct": 19.9,
    "margin": 59.2,
    "winner": "DEM",
    "partisan_lean": "Strong D"
  },
  ...
]
```

### `GET /api/elections/summary`
Returns statewide totals per election — used by the counter bar and statewide card.

### `GET /api/swings?pair=Presidential+2020→2024`
Returns swing data, optionally filtered by `pair`. Fields include `swing_pp` (percentage points), `margin_from`, `margin_to`, `swing_dir` (Toward D / Toward R / Stable).

### `GET /api/swings/pairs`
Returns the list of available swing pairs based on which elections are loaded.

---

## Dashboard Features

### Elections tab
- **Statewide card** — Dem/Rep vote share + margin for selected election
- **Key county results** — Fulton, DeKalb, Gwinnett, Cobb, Henry, Forsyth, Cherokee, Douglas, Rockdale, Dougherty, Muscogee, Chatham + 5 largest remaining
- **Choropleth map** — counties colored by margin (dark blue = Strong D, dark red = Strong R)
- **County tooltip** — hover any county for exact percentages

### Swings tab
- **Pair summary** — count of counties toward D / R / Stable
- **Top 8 toward D** — ranked by swing magnitude with from→to margin bars
- **Top 8 toward R** — same
- **Trend sparkline** — presidential margins over all loaded years

### Compare tab
- **Presidential statewide trend table** — all loaded presidential years side by side
- **Suburban county shift table** — Gwinnett, Cobb, Henry, Forsyth, Cherokee, Douglas, Fayette, Paulding across all presidential years

### Map modes
Toggle between **Elections** (margin choropleth) and **Swings** (swing magnitude choropleth) using the pill at the bottom of the map.

### Export
Each tab has a **Export CSV** button that downloads the currently displayed data.

---

## Adding Elections for Other States

The pipeline is state-agnostic. To run for a different state:

```bash
python scripts/fetch_election_data.py --state NC
python scripts/fetch_election_data.py --state PA
python scripts/fetch_election_data.py --state AZ
```

The MIT countypres file (`countypres_2000_2024.csv`) covers all 50 states — drop it in `data/raw/elections/` and it will filter automatically.

---

## Troubleshooting

**Map counties not shading:**
- Check browser console for `GA counties loaded: 159` — if missing, the GeoJSON fetch from GitHub failed (network issue)
- Verify the API is returning data: `curl http://localhost:8000/api/elections/summary`

**Swing tab shows no data:**
- You need at least 2 elections with matching office types loaded
- Check `data/parquet/dim_swings.parquet` exists after running the pipeline

**Token error on analytics page:**
- Make sure the `/frontend/ui_elections.html` route in `main.py` comes **before** the `app.mount("/frontend", ...)` line
- Verify: `curl -s http://localhost:8000/frontend/ui_elections.html | grep MAPBOX_TOKEN`

**GA SoS Excel not parsing:**
- File must have a `Precinct Results` sheet — download County Summary export, not the statewide summary
- Filename must contain office keyword: `governor`, `senate`, or `runoff`

---

## File Reference

```
~/codebox/fdga/
  main.py                          FastAPI app + API endpoints
  scripts/
    fetch_election_data.py         Election data pipeline
  data/
    raw/elections/                 Drop source CSV/Excel files here
    parquet/
      dim_elections.parquet        County results per election
      dim_swings.parquet           Swing analysis
  frontend/
    ui_elections.html              Analytics dashboard
  index.html                       Main redistricting map
  js/
    config.js                      Mapbox token + district map config
    map.js                         Main map interactions
    chat.js                        AI chat panel
```