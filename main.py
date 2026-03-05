"""
Fair Districts GA — FastAPI Application
"""

import os, json, math, hashlib, sqlite3
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

BASE_DIR   = Path(__file__).parent
DATA_DIR   = Path(os.getenv("LOCAL_DATA_DIR", str(BASE_DIR / "data")))
CHARTS_DIR = DATA_DIR / "charts"
CHARTS_DIR.mkdir(parents=True, exist_ok=True)

# ── Narrative SQLite cache ────────────────────────────────────────────────────
_NARRATIVE_DB = DATA_DIR / "narratives.db"

def _init_narrative_db():
    con = sqlite3.connect(_NARRATIVE_DB)
    con.execute("""
        CREATE TABLE IF NOT EXISTS narratives (
            chamber        TEXT    NOT NULL,
            district       INTEGER NOT NULL,
            data_hash      TEXT    NOT NULL,
            narrative      TEXT    NOT NULL,
            red_flag_level TEXT,
            red_flag_reason TEXT,
            advocate_points TEXT,
            fair_map_note   TEXT,
            model_source    TEXT,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (chamber, district)
        )
    """)
    con.commit()
    con.close()

def _parquet_hash() -> str:
    """Short hash derived from district_stats.parquet mtime — changes on re-ingest."""
    p = DATA_DIR / "parquet" / "district_stats.parquet"
    if p.exists():
        return hashlib.md5(str(p.stat().st_mtime_ns).encode()).hexdigest()[:12]
    return "unknown"

def _narrative_cache_get(chamber: str, district: int, data_hash: str) -> dict | None:
    con = sqlite3.connect(_NARRATIVE_DB)
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT * FROM narratives WHERE chamber=? AND district=? AND data_hash=?",
        (chamber, district, data_hash)
    ).fetchone()
    con.close()
    if row:
        return dict(row)
    return None

def _narrative_cache_set(chamber: str, district: int, data_hash: str, result: dict):
    advocate_json = json.dumps(result.get("advocate_points") or [])
    con = sqlite3.connect(_NARRATIVE_DB)
    con.execute("""
        INSERT INTO narratives
            (chamber, district, data_hash, narrative, red_flag_level,
             red_flag_reason, advocate_points, fair_map_note, model_source)
        VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT(chamber, district) DO UPDATE SET
            data_hash=excluded.data_hash,
            narrative=excluded.narrative,
            red_flag_level=excluded.red_flag_level,
            red_flag_reason=excluded.red_flag_reason,
            advocate_points=excluded.advocate_points,
            fair_map_note=excluded.fair_map_note,
            model_source=excluded.model_source,
            created_at=CURRENT_TIMESTAMP
    """, (
        chamber, district, data_hash,
        result.get("narrative") or "",
        result.get("red_flag_level"), result.get("red_flag_reason"),
        advocate_json,
        result.get("fair_map_note"),
        result.get("source"),
    ))
    con.commit()
    con.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting Fair Districts GA...")
    _init_narrative_db()
    data_files = list(DATA_DIR.glob("*_districts.csv"))
    print(f"  Data: {len(data_files)} district CSV files")
    print(f"  LLM: {os.getenv('LLM_PROVIDER', 'ollama')}")
    print(f"  Narrative cache: {_NARRATIVE_DB}")
    print(f"  Frontend: http://localhost:{os.getenv('PORT', 8000)}")
    yield
    print("Shutting down.")


app = FastAPI(title="Fair Districts GA", version="2.0.0", lifespan=lifespan)

# In-memory cache for district metrics — data is static at runtime, no TTL needed
_metrics_cache: dict[str, dict] = {}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Static mounts — these must come AFTER all @app.get routes
# (mounted at bottom of file)

# ── Frontend ──────────────────────────────────────────────────────────────────
@app.get("/")
async def serve_frontend():
    token = os.getenv("MAPBOX_TOKEN", "")
    html  = (BASE_DIR / "index.html").read_text()
    html  = html.replace("</head>", f'\n  <script>window.MAPBOX_TOKEN = "{token}";</script>\n</head>')
    return HTMLResponse(content=html)

@app.get("/frontend/ui_elections.html")
async def serve_analytics():
    token = os.getenv("MAPBOX_TOKEN", "")
    html  = (BASE_DIR / "frontend" / "ui_elections.html").read_text()
    html  = html.replace("</head>", f'\n  <script>window.MAPBOX_TOKEN = "{token}";</script>\n</head>')
    return HTMLResponse(content=html)

# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    data_files = list(DATA_DIR.glob("*_districts.csv"))
    return {
        "status": "ok",
        "llm_provider": os.getenv("LLM_PROVIDER", "ollama"),
        "data_files": len(data_files),
        "mapbox_token_set": bool(os.getenv("MAPBOX_TOKEN")),
    }

# ── Elections ─────────────────────────────────────────────────────────────────
@app.get("/api/elections")
async def get_elections():
    ep = DATA_DIR / "parquet" / "dim_elections.parquet"
    if not ep.exists():
        raise HTTPException(status_code=404, detail="Run fetch_election_data.py first")
    import duckdb
    rows = duckdb.execute(f"""
        SELECT election_id, year, office, label, county,
               dem_votes, rep_votes, total_votes,
               ROUND(dem_pct*100,1) as dem_pct,
               ROUND(rep_pct*100,1) as rep_pct,
               ROUND(margin*100,1)  as margin,
               winner, partisan_lean
        FROM read_parquet('{ep}')
        ORDER BY year, county
    """).df().to_dict(orient="records")
    return rows

@app.get("/api/elections/summary")
async def get_elections_summary():
    ep = DATA_DIR / "parquet" / "dim_elections.parquet"
    if not ep.exists():
        raise HTTPException(status_code=404, detail="Run fetch_election_data.py first")
    import duckdb
    rows = duckdb.execute(f"""
        SELECT election_id, year, office, label,
               COUNT(DISTINCT county)                          AS counties,
               SUM(dem_votes)                                  AS dem_votes,
               SUM(rep_votes)                                  AS rep_votes,
               SUM(total_votes)                                AS total_votes,
               ROUND(SUM(dem_votes)*100.0/SUM(total_votes),1) AS dem_pct,
               ROUND(SUM(rep_votes)*100.0/SUM(total_votes),1) AS rep_pct,
               ROUND((SUM(dem_votes)-SUM(rep_votes))*100.0/SUM(total_votes),1) AS margin,
               SUM(CASE WHEN winner='DEM' THEN 1 ELSE 0 END)  AS dem_counties,
               SUM(CASE WHEN winner='REP' THEN 1 ELSE 0 END)  AS rep_counties
        FROM read_parquet('{ep}')
        GROUP BY election_id, year, office, label
        ORDER BY year
    """).df().to_dict(orient="records")
    return rows

# ── Swings ────────────────────────────────────────────────────────────────────
@app.get("/api/swings/pairs")
async def get_swing_pairs():
    sp = DATA_DIR / "parquet" / "dim_swings.parquet"
    if not sp.exists():
        raise HTTPException(status_code=404, detail="Run fetch_election_data.py first")
    import duckdb
    rows = duckdb.execute(f"""
        SELECT DISTINCT swing_label, from_id, to_id, year_from, year_to
        FROM read_parquet('{sp}')
        ORDER BY year_from
    """).df().to_dict(orient="records")
    return rows

@app.get("/api/swings")
async def get_swings(pair: str = None):
    sp = DATA_DIR / "parquet" / "dim_swings.parquet"
    if not sp.exists():
        raise HTTPException(status_code=404, detail="Run fetch_election_data.py first")
    import duckdb
    sql = f"""
        SELECT county, swing_label, from_id, to_id,
               year_from, year_to,
               ROUND(swing*100,1)    AS swing_pp,
               ROUND(m_from*100,1)   AS margin_from,
               ROUND(m_to*100,1)     AS margin_to,
               swing_dir
        FROM read_parquet('{sp}')
    """
    if pair:
        rows = duckdb.execute(sql + " WHERE swing_label = ? ORDER BY ABS(swing) DESC", [pair]).df().to_dict(orient="records")
    else:
        rows = duckdb.execute(sql + " ORDER BY ABS(swing) DESC").df().to_dict(orient="records")
    return rows

# ── ACS county socioeconomic data ─────────────────────────────────────────────
@app.get("/api/counties/acs")
async def get_acs():
    p = DATA_DIR / "parquet" / "dim_acs.parquet"
    if not p.exists():
        raise HTTPException(status_code=404, detail="Run scripts/fetch_acs_data.py first")
    import duckdb
    rows = duckdb.execute(f"""
        SELECT county, fips, acs_year,
               total_pop, median_hh_income, median_age, median_earnings,
               pct_poverty, pct_college, pct_owner_occupied,
               pct_broadband, pct_foreign_born,
               pct_white_collar, pct_blue_collar, pct_service,
               pct_long_commute, pct_rent_burdened,
               pct_veteran, pct_black, pct_hispanic, pct_asian, pct_white
        FROM read_parquet('{p}')
        ORDER BY county
    """).df().to_dict(orient="records")
    return rows

# ── District metrics (specific routes BEFORE generic {chamber} route) ─────────
@app.get("/api/districts/{chamber}/metrics")
async def get_district_metrics(chamber: str):
    FILE_MAP = {
        "senate":   "senate_enacted_24_2024update.geojson",
        "house":    "house_enacted_24_2024update.geojson",
        "congress": "congress_enacted_24_2024update.geojson",
    }
    if chamber not in FILE_MAP:
        raise HTTPException(status_code=400, detail=f"Unknown chamber: {chamber}")
    if chamber in _metrics_cache:
        return _metrics_cache[chamber]
    path = DATA_DIR / FILE_MAP[chamber]
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {path.name}")

    geojson  = json.loads(path.read_text())
    results  = []

    for feat in geojson["features"]:
        props    = feat["properties"]
        geom     = feat["geometry"]
        pp_score = polsby_popper(geom)
        dist     = props.get("district")
        partisan = props.get("partisan", 0)
        bvap     = props.get("pct_bvap_al", 0)
        minority = props.get("pct_bp_", 0)

        elections = {
            "g18": props.get("g18_pct_dem"),
            "p20": props.get("p20_pct_dem"),
            "r21": props.get("r21_pct_dem"),
            "g22": props.get("g22_pct_dem"),
            "s22": props.get("s22_pct_dem"),
        }
        valid_elections = {k: v for k, v in elections.items() if v is not None}
        avg_dem = sum(valid_elections.values()) / len(valid_elections) if valid_elections else None

        dem_share = partisan
        rep_share = 1 - partisan
        if dem_share > 0.5:
            wasted_dem = dem_share - 0.5
            wasted_rep = rep_share
            winner = "DEM"
        else:
            wasted_rep = rep_share - 0.5
            wasted_dem = dem_share
            winner = "REP"

        results.append({
            "district":               dist,
            "polsby_popper":          round(pp_score, 3) if pp_score else None,
            "compactness_grade":      compactness_grade(pp_score),
            "partisan_dem_pct":       round(partisan * 100, 1),
            "winner":                 winner,
            "competitive":            abs(partisan - 0.5) < 0.05,
            "packed":                 partisan > 0.65 or partisan < 0.35,
            "avg_dem_pct":            round(avg_dem * 100, 1) if avg_dem else None,
            "wasted_dem_share":       round(wasted_dem, 4),
            "wasted_rep_share":       round(wasted_rep, 4),
            "majority_minority":      minority > 0.50,
            "near_majority_minority": 0.40 <= minority <= 0.50,
            "pct_bvap":               round(bvap * 100, 1),
            "pct_minority_vap":       round(minority * 100, 1),
            "pop":                    props.get("pop"),
            "tvap":                   props.get("tvap"),
            "elections":              {k: round(v * 100, 1) for k, v in valid_elections.items()},
        })

    total_wasted_dem = sum(r["wasted_dem_share"] for r in results)
    total_wasted_rep = sum(r["wasted_rep_share"] for r in results)
    n = len(results)
    efficiency_gap = (total_wasted_dem - total_wasted_rep) / n if n else 0

    pops = [r["pop"] for r in results if r["pop"]]
    ideal_pop = sum(pops) / len(pops) if pops else 0
    for r in results:
        if r["pop"] and ideal_pop:
            r["pop_deviation_pct"] = round((r["pop"] - ideal_pop) / ideal_pop * 100, 2)

    result = {
        "chamber":             chamber,
        "n_districts":         n,
        "efficiency_gap":      round(efficiency_gap * 100, 2),
        "efficiency_gap_note": "Positive = favors Republicans. >8% is considered significant bias.",
        "ideal_population":    round(ideal_pop),
        "n_competitive":       sum(1 for r in results if r["competitive"]),
        "n_packed":            sum(1 for r in results if r["packed"]),
        "n_majority_minority": sum(1 for r in results if r["majority_minority"]),
        "avg_compactness":     round(sum(r["polsby_popper"] for r in results if r["polsby_popper"]) / n, 3),
        "districts":           sorted(results, key=lambda x: x["district"]),
    }
    _metrics_cache[chamber] = result
    return result

@app.get("/api/narratives/recent")
async def get_recent_narratives(limit: int = 10):
    """Return the most recently generated narratives from SQLite cache."""
    con = sqlite3.connect(_NARRATIVE_DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT chamber, district, red_flag_level, red_flag_reason, model_source, created_at "
        "FROM narratives ORDER BY created_at DESC LIMIT ?",
        (min(limit, 50),)
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


@app.get("/api/districts/{chamber}/{district_id}/narrative")
async def get_district_narrative(chamber: str, district_id: int, force: bool = False):
    # ── Cache lookup ─────────────────────────────────────────────────────────
    data_hash = _parquet_hash()
    if not force:
        cached = _narrative_cache_get(chamber, district_id, data_hash)
        if cached:
            advocate_points = []
            try:
                advocate_points = json.loads(cached.get("advocate_points") or "[]")
            except Exception:
                pass
            return {
                "district":       district_id,
                "chamber":        chamber,
                "narrative":      cached["narrative"],
                "red_flag_level": cached.get("red_flag_level"),
                "red_flag_reason":cached.get("red_flag_reason"),
                "advocate_points":advocate_points,
                "fair_map_note":  cached.get("fair_map_note"),
                "source":         cached.get("model_source"),
                "cached":         True,
                "cached_at":      cached.get("created_at"),
            }

    metrics_response = await get_district_metrics(chamber)
    dist_data = next((d for d in metrics_response["districts"] if d["district"] == district_id), None)
    if not dist_data:
        raise HTTPException(status_code=404, detail=f"District {district_id} not found")

    efficiency_gap = metrics_response["efficiency_gap"]
    elections_text = "\n".join(f"- {k}: {v}%" for k, v in dist_data.get("elections", {}).items())

    # Pull ACS data for counties that overlap this district
    # For now we use statewide ACS context; per-district ACS requires spatial join
    acs_context = ""
    try:
        import duckdb
        acs_path = DATA_DIR / "parquet" / "dim_acs.parquet"
        if acs_path.exists():
            acs_state = duckdb.execute(f"""
                SELECT
                    ROUND(AVG(median_hh_income),0)   AS avg_income,
                    ROUND(AVG(pct_poverty),1)         AS avg_poverty,
                    ROUND(AVG(pct_college),1)         AS avg_college,
                    ROUND(AVG(pct_broadband),1)       AS avg_broadband,
                    ROUND(AVG(pct_blue_collar),1)     AS avg_blue_collar
                FROM read_parquet('{acs_path}')
            """).df().to_dict(orient="records")[0]
            acs_context = f"""
STATEWIDE SOCIOECONOMIC CONTEXT (ACS 2022):
- Average median household income: ${acs_state['avg_income']:,.0f}
- Average poverty rate: {acs_state['avg_poverty']}%
- Average college attainment: {acs_state['avg_college']}%
- Average broadband access: {acs_state['avg_broadband']}%
- Average blue-collar employment: {acs_state['avg_blue_collar']}%
"""
    except Exception:
        pass

    prompt = f"""You are an expert analyst in redistricting, voting rights law, and Georgia politics.
Write a clear, factual 3-4 paragraph narrative about the legislative district below.
Your audience is an educated non-expert — a journalist, advocate, or engaged citizen.

IMPORTANT FRAMING NOTES:
- "Packing" a majority-minority district means concentrating minority voters so heavily that
  their votes are wasted on supermajority wins, potentially reducing their influence statewide.
  This is different from disenfranchisement — the community elects its preferred candidate,
  but their collective power is diluted by being crammed into one district rather than
  influencing two or three.
- A low Polsby-Popper score (below 0.20) indicates an irregularly shaped district,
  which often signals boundaries drawn for political rather than geographic reasons.
- The efficiency gap measures statewide partisan bias. At 8.73% favoring Republicans,
  Georgia's Senate map crosses the threshold courts have used to identify significant gerrymandering.
- Do NOT speculate beyond the data provided. Do NOT invent place names or events.
- End with one sentence on what fair redistricting would examine for this district.

DISTRICT DATA:
Chamber: {chamber.upper()}
District: {district_id}
Population: {dist_data.get('pop', 'N/A'):,} (deviation from ideal: {dist_data.get('pop_deviation_pct', 'N/A')}%)
Voting Age Population: {dist_data.get('tvap', 'N/A'):,}

DEMOGRAPHICS (% of Voting Age Population):
- Black VAP: {dist_data['pct_bvap']}%
- Total Minority VAP: {dist_data['pct_minority_vap']}%
- Majority-minority district: {'Yes' if dist_data['majority_minority'] else 'No'}

PARTISAN LEAN & COMPETITIVENESS:
- Partisan index: {dist_data['partisan_dem_pct']}% Democratic
- Projected winner: {dist_data['winner']}
- Competitive (within 5pp of toss-up): {'Yes' if dist_data['competitive'] else 'No'}
- Packed (>65% or <35% for one party): {'Yes' if dist_data['packed'] else 'No'}
- Wasted Democratic vote share: {round(dist_data['wasted_dem_share']*100,1)}%
- Wasted Republican vote share: {round(dist_data['wasted_rep_share']*100,1)}%

ELECTION HISTORY (% Democratic):
{elections_text}

COMPACTNESS:
- Polsby-Popper score: {dist_data['polsby_popper']} / 1.0 (grade: {dist_data['compactness_grade']})
- Interpretation: {'Severely irregular shape — boundaries are not geographically motivated' if dist_data['polsby_popper'] and dist_data['polsby_popper'] < 0.15 else 'Moderately irregular shape' if dist_data['polsby_popper'] and dist_data['polsby_popper'] < 0.25 else 'Reasonably compact'}

STATEWIDE MAP CONTEXT:
- Senate efficiency gap: {efficiency_gap}% (favors {'Republicans' if efficiency_gap > 0 else 'Democrats'})
- Only 1 of 56 Senate districts is competitive
- 35 of 56 districts are packed
- 22 of 56 districts are majority-minority
{acs_context}
Write the narrative now. Be specific, direct, and analytical. No bullet points."""

    import httpx

    def _build_result(narrative: str, source: str) -> dict:
        result = {"district": district_id, "chamber": chamber,
                  "narrative": narrative, "source": source, "data": dist_data, "cached": False}
        _narrative_cache_set(chamber, district_id, data_hash, result)
        return result

    # Try Ollama
    try:
        ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        ollama_model = os.getenv("OLLAMA_MODEL", "llama3:8b")
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{ollama_host}/api/generate", json={
                "model": ollama_model,
                "prompt": prompt,
                "stream": False,
            })
            if r.status_code == 200:
                narrative = r.json().get("response", "").strip()
                return _build_result(narrative, f"ollama/{ollama_model}")
    except Exception as e:
        print(f"Ollama error: {e}")

    # Try Groq
    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {groq_key}"},
                    json={"model": "llama3-8b-8192",
                          "messages": [{"role": "user", "content": prompt}],
                          "max_tokens": 600}
                )
                if r.status_code == 200:
                    narrative = r.json()["choices"][0]["message"]["content"].strip()
                    return _build_result(narrative, "groq")
        except Exception:
            pass

    return {"district": district_id, "chamber": chamber, "narrative": None,
            "source": "none", "data": dist_data, "cached": False,
            "error": "No LLM available. Set GROQ_API_KEY or run Ollama locally."}

# ── Generic district data (MUST come after specific routes above) ─────────────
@app.get("/api/districts/{chamber}")
async def get_districts(chamber: str):
    FILE_MAP = {
        "senate":   "senate_enacted_24_2024update.geojson",
        "house":    "house_enacted_24_2024update.geojson",
        "congress": "congress_enacted_24_2024update.geojson",
    }
    if chamber not in FILE_MAP:
        raise HTTPException(status_code=400, detail=f"Unknown chamber: {chamber}")
    path = DATA_DIR / FILE_MAP[chamber]
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {path.name}")
    geojson = json.loads(path.read_text())
    rows = []
    for f in geojson["features"]:
        p = f["properties"]
        rows.append({
            "district":    p.get("district"),
            "pop":         p.get("pop"),
            "tvap":        p.get("tvap"),
            "pct_bvp":     round(p.get("pct_bvp", 0) * 100, 1),
            "pct_hvp":     round(p.get("pct_hvp", 0) * 100, 1),
            "pct_avp":     round(p.get("pct_avp", 0) * 100, 1),
            "pct_wvap_al": round(p.get("pct_wvap_al", 0) * 100, 1),
            "pct_bp_":     round(p.get("pct_bp_", 0) * 100, 1),
            "partisan":    round(p.get("partisan", 0) * 100, 1),
            "g18_pct_dem": round(p.get("g18_pct_dem", 0) * 100, 1),
            "p20_pct_dem": round(p.get("p20_pct_dem", 0) * 100, 1),
            "r21_pct_dem": round(p.get("r21_pct_dem", 0) * 100, 1),
            "g22_pct_dem": round(p.get("g22_pct_dem", 0) * 100, 1),
            "s22_pct_dem": round(p.get("s22_pct_dem", 0) * 100, 1),
        })
    rows.sort(key=lambda x: x["district"])
    return rows

# ── Geometry helpers ──────────────────────────────────────────────────────────
def polygon_area_perimeter(coords):
    area = perim = 0.0
    n = len(coords)
    for i in range(n):
        x1, y1 = coords[i]
        x2, y2 = coords[(i + 1) % n]
        area  += x1 * y2 - x2 * y1
        perim += math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
    return abs(area) / 2, perim

def polsby_popper(geom):
    try:
        if geom["type"] == "Polygon":
            area, perim = polygon_area_perimeter(geom["coordinates"][0])
        elif geom["type"] == "MultiPolygon":
            area = perim = 0.0
            for poly in geom["coordinates"]:
                a, p = polygon_area_perimeter(poly[0])
                area += a; perim += p
        else:
            return None
        return (4 * math.pi * area) / (perim ** 2) if perim else None
    except Exception:
        return None

def compactness_grade(score):
    if score is None: return "N/A"
    if score >= 0.40: return "A"
    if score >= 0.30: return "B"
    if score >= 0.20: return "C"
    if score >= 0.10: return "D"
    return "F"

# ── Chat endpoints ────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    question: str
    mode: str = "auto"

class ChatResponse(BaseModel):
    answer: str
    chart_url: str | None = None
    data_summary: str = ""
    question: str = ""

@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    try:
        from backend.crews.analysis_crew import answer_question
        result = await answer_question(req.question)
        chart_url = f"/charts/{Path(result.chart_path).name}" if result.has_chart else None
        return ChatResponse(answer=result.answer, chart_url=chart_url,
                            data_summary=result.data_summary, question=req.question)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat/quick", response_model=ChatResponse)
async def chat_quick(req: ChatRequest):
    try:
        from backend.crews.analysis_crew import FairDistrictsGACrew
        crew   = FairDistrictsGACrew()
        result = crew.quick_answer(req.question)
        return ChatResponse(answer=result.answer, data_summary=result.data_summary, question=req.question)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/telegram")
async def telegram_webhook(update: dict):
    try:
        from backend.routers.telegram import handle_update
        await handle_update(update)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Static mounts (MUST be last — after all @app.get routes) ─────────────────
app.mount("/data",     StaticFiles(directory=str(DATA_DIR)),               name="data")
app.mount("/charts",   StaticFiles(directory=str(CHARTS_DIR)),             name="charts")
app.mount("/css",      StaticFiles(directory=str(BASE_DIR / "css")),       name="css")
app.mount("/js",       StaticFiles(directory=str(BASE_DIR / "js")),        name="js")
app.mount("/img",      StaticFiles(directory=str(BASE_DIR / "img")),       name="img")
app.mount("/frontend", StaticFiles(directory=str(BASE_DIR / "frontend")), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0",
                port=int(os.getenv("PORT", 8000)), reload=True)