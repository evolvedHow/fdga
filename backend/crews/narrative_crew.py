"""
Narrative Crew — 6-Agent Redistricting Story Generator
========================================================
Coordinates six specialized agents to produce a deep, accurate,
plain-English narrative about any Georgia legislative district.

Usage:
    crew = NarrativeCrew()
    result = crew.analyze_district("senate", 38)
    print(result.narrative)
    print(result.red_flag_level)

    # Batch all districts
    results = crew.analyze_chamber("senate")
"""

import os
import json
import logging
import duckdb

# Suppress LiteLLM's noisy fastapi_sso import error — it's a logging bug, not functional
logging.getLogger("LiteLLM").setLevel(logging.CRITICAL)
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from crewai import Crew, Task, Process

from backend.agents.redistricting_agents import create_redistricting_agents


# ── Result data class ─────────────────────────────────────────────────────────

@dataclass
class NarrativeResult:
    """Structured result from the narrative crew."""
    chamber:          str
    district:         int
    narrative:        str
    red_flag_level:   str        # HIGH / MODERATE / LOW / NEUTRAL
    red_flag_reason:  str
    advocate_points:  list[str]  # Up to 3 key data points to highlight
    fair_map_note:    str        # What a fair map would address
    source:           str        # Which LLM produced this
    legal_finding:    str = ""    # Legal vulnerability assessment
    data:             dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "chamber":         self.chamber,
            "district":        self.district,
            "narrative":       self.narrative,
            "red_flag_level":  self.red_flag_level,
            "red_flag_reason": self.red_flag_reason,
            "advocate_points": self.advocate_points,
            "fair_map_note":   self.fair_map_note,
            "legal_finding":   self.legal_finding,
            "source":          self.source,
            "data":            self.data,
        }


# ── Data loader ───────────────────────────────────────────────────────────────

def load_district_data(chamber: str, district_id: int) -> dict:
    """
    Load all available data for a district from parquet files and GeoJSON.
    Returns a unified dict the agents can work from.
    """
    import math

    data_dir = Path(os.getenv("LOCAL_DATA_DIR", "data"))

    FILE_MAP = {
        "senate":   "senate_enacted_24_2024update.geojson",
        "house":    "house_enacted_24_2024update.geojson",
        "congress": "congress_enacted_24_2024update.geojson",
    }

    result = {"chamber": chamber, "district": district_id}

    # ── District GeoJSON (demographics + elections + geometry) ────────────────
    geojson_path = data_dir / FILE_MAP[chamber]
    if geojson_path.exists():
        with open(geojson_path) as f:
            geojson = json.load(f)
        feat = next(
            (ft for ft in geojson["features"]
             if ft["properties"].get("district") == district_id), None
        )
        if feat:
            p = feat["properties"]
            result.update({
                "pop":           p.get("pop"),
                "tvap":          p.get("tvap"),
                "pct_bvap":      round(p.get("pct_bvap_al", 0) * 100, 1),
                "pct_hvap":      round(p.get("pct_hvp", 0) * 100, 1),
                "pct_avap":      round(p.get("pct_avap_al", 0) * 100, 1),
                "pct_wvap":      round(p.get("pct_wvap_al", 0) * 100, 1),
                "pct_minority":  round(p.get("pct_bp_", 0) * 100, 1),
                "partisan_dem":  round(p.get("partisan", 0) * 100, 1),
                "elections": {
                    "Gov 2018":    round(p.get("g18_pct_dem", 0) * 100, 1),
                    "Pres 2020":   round(p.get("p20_pct_dem", 0) * 100, 1),
                    "Runoff 2021": round(p.get("r21_pct_dem", 0) * 100, 1),
                    "Gov 2022":    round(p.get("g22_pct_dem", 0) * 100, 1),
                    "Sen 2022":    round(p.get("s22_pct_dem", 0) * 100, 1),
                },
            })

            # Polsby-Popper compactness
            geom = feat["geometry"]
            pp = _polsby_popper(geom)
            result["polsby_popper"] = round(pp, 3) if pp else None
            result["compactness_grade"] = _compactness_grade(pp)

    # ── Population deviation ──────────────────────────────────────────────────
    if geojson_path.exists():
        with open(geojson_path) as f:
            gj = json.load(f)
        all_pops = [ft["properties"].get("pop", 0) for ft in gj["features"]]
        ideal = sum(all_pops) / len(all_pops) if all_pops else 0
        if result.get("pop") and ideal:
            result["pop_deviation_pct"] = round(
                (result["pop"] - ideal) / ideal * 100, 2
            )
        result["ideal_pop"] = round(ideal)

    # ── Efficiency gap (chamber-level) ────────────────────────────────────────
    if geojson_path.exists():
        with open(geojson_path) as f:
            gj = json.load(f)
        wasted_dem = wasted_rep = 0.0
        n = len(gj["features"])
        for ft in gj["features"]:
            partisan = ft["properties"].get("partisan", 0.5)
            if partisan > 0.5:
                wasted_dem += partisan - 0.5
                wasted_rep += 1 - partisan
            else:
                wasted_rep += (1 - partisan) - 0.5
                wasted_dem += partisan
        result["chamber_efficiency_gap"] = round(
            (wasted_dem - wasted_rep) / n * 100, 2
        ) if n else 0
        result["chamber_n_districts"] = n

    # ── ACS socioeconomic data ────────────────────────────────────────────────
    acs_path = data_dir / "parquet" / "dim_acs.parquet"
    if acs_path.exists():
        try:
            # Get statewide averages for context
            state_avg = duckdb.execute(f"""
                SELECT
                    ROUND(AVG(median_hh_income), 0)    AS avg_income,
                    ROUND(AVG(pct_poverty), 1)          AS avg_poverty,
                    ROUND(AVG(pct_college), 1)          AS avg_college,
                    ROUND(AVG(pct_broadband), 1)        AS avg_broadband,
                    ROUND(AVG(pct_long_commute), 1)     AS avg_long_commute,
                    ROUND(AVG(pct_blue_collar), 1)      AS avg_blue_collar,
                    ROUND(AVG(pct_rent_burdened), 1)    AS avg_rent_burdened,
                    ROUND(AVG(pct_veteran), 1)          AS avg_veteran,
                    ROUND(AVG(pct_foreign_born), 1)     AS avg_foreign_born
                FROM read_parquet('{acs_path}')
            """).df().to_dict(orient="records")[0]
            result["acs_state_avg"] = state_avg
        except Exception as e:
            result["acs_state_avg"] = {}

    # ── County election data for context ─────────────────────────────────────
    elections_path = data_dir / "parquet" / "dim_elections.parquet"
    if elections_path.exists():
        try:
            # Most recent presidential for context
            recent = duckdb.execute(f"""
                SELECT ROUND(AVG(CASE WHEN winner='DEM' THEN 1.0 ELSE 0.0 END)*100,1)
                    AS pct_dem_counties
                FROM read_parquet('{elections_path}')
                WHERE office = 'president'
                  AND year = (SELECT MAX(year) FROM read_parquet('{elections_path}')
                              WHERE office='president')
            """).df().to_dict(orient="records")
            if recent:
                result["state_pct_dem_counties_recent"] = recent[0]["pct_dem_counties"]
        except Exception:
            pass

    return result


# ── Geometry helpers ──────────────────────────────────────────────────────────

def _polygon_area_perimeter(coords):
    area = perim = 0.0
    import math
    n = len(coords)
    for i in range(n):
        x1, y1 = coords[i]
        x2, y2 = coords[(i + 1) % n]
        area  += x1 * y2 - x2 * y1
        perim += math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
    return abs(area) / 2, perim

def _polsby_popper(geom):
    import math
    try:
        if geom["type"] == "Polygon":
            area, perim = _polygon_area_perimeter(geom["coordinates"][0])
        elif geom["type"] == "MultiPolygon":
            area = perim = 0.0
            for poly in geom["coordinates"]:
                a, p = _polygon_area_perimeter(poly[0])
                area += a; perim += p
        else:
            return None
        return (4 * math.pi * area) / (perim ** 2) if perim else None
    except Exception:
        return None

def _compactness_grade(score):
    if score is None:  return "N/A"
    if score >= 0.40:  return "A"
    if score >= 0.30:  return "B"
    if score >= 0.20:  return "C"
    if score >= 0.10:  return "D"
    return "F"


# ── Crew builder ──────────────────────────────────────────────────────────────

class NarrativeCrew:
    """
    6-agent crew for district narrative generation.

    Usage:
        crew = NarrativeCrew()
        result = crew.analyze_district("senate", 38)
    """

    def __init__(self):
        print("Initializing Narrative Crew...")
        (self.demographer,
         self.elections_analyst,
         self.geographer,
         self.socioeconomic_analyst,
         self.legal_analyst,
         self.policy_writer,
         self.critic) = create_redistricting_agents()
        print("  7 agents ready")

    def analyze_district(self, chamber: str, district_id: int) -> NarrativeResult:
        """Run the full 6-agent pipeline for one district."""
        print(f"\nAnalyzing {chamber.upper()} District {district_id}...")

        d = load_district_data(chamber, district_id)
        if not d.get("pop"):
            raise ValueError(f"No data found for {chamber} district {district_id}")

        # Format election history for prompts
        elections_text = "\n".join(
            f"  - {k}: {v}% Democratic" for k, v in d.get("elections", {}).items()
        )

        # Format ACS state averages for context
        avg = d.get("acs_state_avg", {})
        acs_context = f"""
Georgia statewide averages (ACS 2022):
  - Median household income: ${avg.get('avg_income', 'N/A'):,}
  - Poverty rate: {avg.get('avg_poverty', 'N/A')}%
  - College attainment: {avg.get('avg_college', 'N/A')}%
  - Broadband access: {avg.get('avg_broadband', 'N/A')}%
  - Long commute (60+ min): {avg.get('avg_long_commute', 'N/A')}%
  - Blue-collar employment: {avg.get('avg_blue_collar', 'N/A')}%
""" if avg else ""

        chamber_label = chamber.upper()
        packed = d.get("partisan_dem", 50) > 65 or d.get("partisan_dem", 50) < 35
        competitive = abs(d.get("partisan_dem", 50) - 50) < 5
        majority_minority = d.get("pct_minority", 0) > 50
        winner = "DEM" if d.get("partisan_dem", 50) > 50 else "REP"
        wasted_dem = round(max(d.get("partisan_dem", 50)/100 - 0.5, 0), 4) if winner == "DEM" \
                     else round(d.get("partisan_dem", 50)/100, 4)
        wasted_rep = round(max((100-d.get("partisan_dem", 50))/100 - 0.5, 0), 4) if winner == "REP" \
                     else round((100-d.get("partisan_dem", 50))/100, 4)

        # ── Shared data block for all agents ─────────────────────────────────
        data_block = f"""
DISTRICT: {chamber_label} District {district_id}
Population: {d.get('pop', 'N/A'):,} (deviation from ideal: {d.get('pop_deviation_pct', 'N/A')}%)
Voting Age Population: {d.get('tvap', 'N/A'):,}

DEMOGRAPHICS (% of Voting Age Population):
  - Black VAP:    {d.get('pct_bvap', 'N/A')}%
  - Hispanic VAP: {d.get('pct_hvap', 'N/A')}%
  - Asian VAP:    {d.get('pct_avap', 'N/A')}%
  - White VAP:    {d.get('pct_wvap', 'N/A')}%
  - Total Minority VAP: {d.get('pct_minority', 'N/A')}%
  - Majority-minority: {'Yes' if majority_minority else 'No'}

PARTISAN LEAN:
  - Partisan index: {d.get('partisan_dem', 'N/A')}% Democratic
  - Projected winner: {winner}
  - Competitive (within 5pp of 50%): {'Yes' if competitive else 'No'}
  - Packed (>65% or <35%): {'Yes' if packed else 'No'}
  - Wasted Dem share: {round(wasted_dem*100, 1)}%
  - Wasted Rep share: {round(wasted_rep*100, 1)}%

ELECTION HISTORY:
{elections_text}

COMPACTNESS:
  - Polsby-Popper score: {d.get('polsby_popper', 'N/A')} / 1.0
  - Grade: {d.get('compactness_grade', 'N/A')}

CHAMBER CONTEXT ({chamber_label}):
  - Efficiency gap: {d.get('chamber_efficiency_gap', 'N/A')}%
    (positive = favors Republicans, >8% = significant bias)
    (packed Democratic districts INCREASE the efficiency gap by generating
     large numbers of wasted Democratic votes — a district packed at 77%+
     Democratic is contributing to this gap, not separate from it)
  - Total districts: {d.get('chamber_n_districts', 'N/A')}
{acs_context}"""

        # ── Task 1: Demographer ───────────────────────────────────────────────
        demog_task = Task(
            description=f"""
Analyze the demographic composition and VRA implications of this district.
Use ONLY the data provided below — do not invent or assume additional facts.

{data_block}

Produce a DEMOGRAPHIC FINDING covering:
1. What the VAP breakdown tells us about this community
2. VRA status: Is this district majority-minority? Is it potentially packed or cracked?
   (Packing = minority voters over-concentrated, wasting their influence on supermajority wins)
   (Cracking = minority community split across districts, unable to form majority anywhere)
3. Population deviation from ideal — is this district properly sized?
4. Confidence level: High / Medium / Low

Be specific with numbers. 150-200 words.
""",
            expected_output="DEMOGRAPHIC FINDING: 150-200 word structured analysis with VRA assessment",
            agent=self.demographer,
        )

        # ── Task 2: Elections Analyst ─────────────────────────────────────────
        elections_task = Task(
            description=f"""
Analyze the electoral history and partisan dynamics of this district.
Use ONLY the data provided below — do not invent or assume additional facts.

{data_block}

Produce an ELECTORAL FINDING covering:
1. Is this district competitive, packed Democratic, or packed Republican?
2. What does the election history trend show? (Stable? Shifting? Volatile?)
3. How much does this district contribute to the statewide efficiency gap?
4. What is the practical effect — are votes here meaningful or predetermined?

Be specific with numbers. Note if the partisan lean has changed across the
five elections in the data. 150-200 words.
""",
            expected_output="ELECTORAL FINDING: 150-200 word structured analysis with competitiveness assessment",
            agent=self.elections_analyst,
        )

        # ── Task 3: Geographer ────────────────────────────────────────────────
        geog_task = Task(
            description=f"""
Analyze the geographic integrity of this district's boundaries.
Use ONLY the data provided below — do not invent or assume additional facts.

{data_block}

Produce a GEOGRAPHIC FINDING covering:
1. What does the Polsby-Popper score tell us? Put it in context:
   - Is this score typical for Georgia districts or an outlier?
   - Does the grade (A/B/C/D/F) suggest natural geography or political drawing?
2. Combined with the demographic and partisan data, does the shape raise concerns?
3. Red flag level: None / Moderate / High — with one-sentence justification

Note: Some irregular shapes follow rivers, coastlines, or county lines.
Without a visual, we can flag irregularity but not confirm its cause.
100-150 words.
""",
            expected_output="GEOGRAPHIC FINDING: 100-150 word compactness analysis with red flag assessment",
            agent=self.geographer,
        )

        # ── Task 4: Socioeconomic Analyst ─────────────────────────────────────
        socio_task = Task(
            description=f"""
Analyze the socioeconomic character of this district using the ACS context provided.
Use ONLY the data provided below — do not invent county names or specific local facts.

{data_block}

Note: We have ACS data at the county level but not yet district level.
Use the statewide averages as context for what we know about majority-minority
districts and their typical socioeconomic profiles in Georgia.

Produce a SOCIOECONOMIC FINDING covering:
1. Based on the demographic profile, what economic circumstances likely
   characterize this community? (Connect minority VAP % to typical ACS patterns
   in Georgia — e.g., majority-Black districts in Georgia often have higher poverty
   rates and lower broadband access than the state average)
2. What policy issues would this community most need representation on?
3. Does a packed district — where votes are predetermined — reduce the community's
   legislative influence on those issues?

Be careful to distinguish what the data shows vs. what is inferred.
100-150 words.
""",
            expected_output="SOCIOECONOMIC FINDING: 100-150 word community profile with representation implications",
            agent=self.socioeconomic_analyst,
        )


        # ── Task 5: Legal Analyst ─────────────────────────────────────────────
        legal_task = Task(
            description=f"""
Analyze the legal vulnerabilities of this district under federal and Georgia state law.
Use ONLY the data provided below — do not invent facts or assume local geography.

{data_block}

Produce a LEGAL FINDING covering:
1. Which legal standards apply to this district based on its data profile
2. Viable claims: What specific facts trigger which legal standard
   - VRA Section 2 packing/cracking?
   - Shaw v. Reno racial predominance? (requires PP <0.15 AND BVAP >55%)
   - Equal population violation? (requires >10% deviation from ideal)
   - State court partisan gerrymandering under Ga. Const. Art. II? 
     (efficiency gap >8% is relevant here — federal courts unavailable after Rucho)
3. Non-viable claims: What the data does NOT support — be explicit
4. Recommended next steps for an advocate or attorney
5. Confidence level: VIABLE CLAIM / POSSIBLE CLAIM / INSUFFICIENT DATA

End with the mandatory disclaimer about attorney review.
150-200 words.
""",
            expected_output="LEGAL FINDING: 150-200 word structured legal vulnerability analysis",
            agent=self.legal_analyst,
        )

        # ── Task 6: Policy Writer ─────────────────────────────────────────────
        write_task = Task(
            description=f"""
You have FIVE expert findings about {chamber_label} District {district_id}:
the Demographer, Elections Analyst, Geographer, Socioeconomic Analyst, and Legal Analyst.
Synthesize them into a single 4-paragraph plain-English narrative.
The Legal Analyst's finding MUST appear in Paragraph 4 — include specific case names
and confidence level. Do not omit the legal analysis.

Original data for reference:
{data_block}

Structure your narrative EXACTLY as follows:
  Paragraph 1 — WHO LIVES HERE: Demographics and community character.
    Lead with the most striking demographic fact. In 1-2 sentences, connect
    the demographic profile to the community's likely economic circumstances
    using the Socioeconomic Analyst's finding (poverty rate context, broadband
    access, housing pressures). Make the human stakes concrete.
  Paragraph 2 — WHAT THE ELECTIONS SHOW (partisan history + competitiveness)
  Paragraph 3 — WHAT THE MAP DOES (shape + boundary implications)
  Paragraph 4 — THE LEGAL PICTURE: Use the Legal Analyst's EXACT findings.
    Name the specific cases and confidence level from the Legal Analyst.
    Include: Shaw v. Reno racial predominance trigger (if applicable),
    VRA Section 2 (packing or cracking), Rucho v. Common Cause (why efficiency
    gap claims must go to Georgia state court, not federal court).
    End with one sentence on what a fair map would need to address.

Requirements:
- Lead paragraph 1 with the most striking demographic fact, NOT "This district..."
- Use specific numbers throughout
- Explain jargon inline on first use
- ~300-400 words total
- Write like journalism, not a legal brief
- Do NOT contradict the expert findings
- Do NOT speculate beyond the data
""",
            expected_output="4-paragraph narrative, ~300-400 words, journalistic tone",
            agent=self.policy_writer,
            context=[demog_task, elections_task, geog_task, socio_task, legal_task],
        )

        # ── Task 7: Critic ────────────────────────────────────────────────────
        critic_task = Task(
            description=f"""
Review the policy writer's narrative for {chamber_label} District {district_id}.
Check it against the raw data and expert findings for accuracy.

Original data:
{data_block}

IMPORTANT: Your primary job is PRESERVATION, not rewriting. The Policy Writer's
narrative is the product. You are a copy editor, not a ghostwriter.

Your output MUST follow this EXACT format:

NARRATIVE:
[Copy the Policy Writer's narrative VERBATIM, paragraph by paragraph.
Make ONLY these targeted changes if needed:
  - Fix any number that does not match the data block (e.g., wrong percentage)
  - If Paragraph 4 is missing case names (Shaw v. Reno, VRA Section 2, Rucho),
    INSERT the missing names into Paragraph 4 only — do not rewrite the paragraph
  - Remove a repeated phrase if a key term appears more than once unnecessarily
Do NOT restructure, summarize, condense, or rewrite any paragraph.
Do NOT change the 4-paragraph headings or journalistic tone.
If you cannot find specific errors, copy the narrative unchanged.]

RED_FLAG_LEVEL: [HIGH / MODERATE / LOW / NEUTRAL]
RED_FLAG_REASON: [One sentence explaining the level]

ADVOCATE_POINTS:
- [Specific data point 1 an advocate should highlight]
- [Specific data point 2]
- [Specific data point 3]

FAIR_MAP_NOTE: [One sentence on what fair redistricting would need to address here]

Check for:
1. Any numbers that don't match the data block above
2. Any causal claims the data can't support
3. REQUIRED: Does Paragraph 4 include specific case names from the Legal Analyst?
   If Shaw v. Reno, VRA Section 2, or Rucho are missing — INSERT them into
   Paragraph 4 only. Do not rewrite other paragraphs.
   The legal finding confidence level must appear in Paragraph 4.
4. Any repetition — "wasted Democratic share" should appear ONCE, not three times
5. Whether the red flag level matches the combined findings:
   HIGH = packed + F/D compactness + significant efficiency gap contribution
   MODERATE = one major concern (packing OR poor compactness, not both)
   LOW = no significant concerns
6. VRA packing framing: If the narrative says packing a majority-minority district
   IS a VRA violation, that framing is wrong — flag it and correct to:
   "excessive packing concentrates minority influence into fewer seats and may
   reduce regional minority representation across neighboring districts."
7. Gingles Precondition 3: If the narrative asserts all three Gingles preconditions
   are met, check whether white-bloc-voting evidence is present in the data.
   If not, correct to: "meets the first two Gingles preconditions; Precondition 3
   (white bloc voting) requires racially polarized voting analysis not available here."
""",
            expected_output="Corrected narrative + RED_FLAG_LEVEL + ADVOCATE_POINTS + FAIR_MAP_NOTE",
            agent=self.critic,
            context=[demog_task, elections_task, geog_task, socio_task, legal_task, write_task],
        )

        # ── Assemble and run ──────────────────────────────────────────────────
        crew = Crew(
            agents=[
                self.demographer,
                self.elections_analyst,
                self.geographer,
                self.socioeconomic_analyst,
                self.legal_analyst,
                self.policy_writer,
                self.critic,
            ],
            tasks=[
                demog_task,
                elections_task,
                geog_task,
                socio_task,
                legal_task,
                write_task,
                critic_task,
            ],
            process=Process.sequential,
            verbose=True,
        )

        crew.kickoff()

        # ── Parse critic output ───────────────────────────────────────────────
        raw = str(critic_task.output or "")
        narrative      = _extract_section(raw, "NARRATIVE:", "RED_FLAG_LEVEL:").strip()
        red_flag_level = _extract_line(raw, "RED_FLAG_LEVEL:").strip()
        red_flag_reason= _extract_line(raw, "RED_FLAG_REASON:").strip()
        fair_map_note  = _extract_line(raw, "FAIR_MAP_NOTE:").strip()
        advocate_block = _extract_section(raw, "ADVOCATE_POINTS:", "FAIR_MAP_NOTE:")
        advocate_points = [
            line.lstrip("- •").strip()
            for line in advocate_block.strip().splitlines()
            if line.strip() and line.strip() not in ("ADVOCATE_POINTS:",)
        ]

        # Extract legal finding from legal task
        legal_finding = str(legal_task.output or "").strip()

        # Fallback: if critic output wasn't structured, use writer output
        if not narrative:
            narrative = str(write_task.output or "")

        llm_source = f"ollama/{os.getenv('OLLAMA_MODEL', 'llama3:8b')}"

        return NarrativeResult(
            chamber=chamber,
            district=district_id,
            narrative=narrative,
            red_flag_level=red_flag_level or "NEUTRAL",
            red_flag_reason=red_flag_reason,
            advocate_points=advocate_points[:3],
            fair_map_note=fair_map_note,
            source=llm_source,
            data=d,
            legal_finding=legal_finding,
        )

    def analyze_chamber(self, chamber: str,
                        district_ids: Optional[list] = None) -> list[NarrativeResult]:
        """
        Run narrative analysis for multiple districts.
        If district_ids is None, analyzes all districts in the chamber.

        Example:
            results = crew.analyze_chamber("senate", [1, 2, 38, 45])
        """
        import json
        from pathlib import Path

        data_dir = Path(os.getenv("LOCAL_DATA_DIR", "data"))
        FILE_MAP = {
            "senate":   "senate_enacted_24_2024update.geojson",
            "house":    "house_enacted_24_2024update.geojson",
            "congress": "congress_enacted_24_2024update.geojson",
        }
        if district_ids is None:
            with open(data_dir / FILE_MAP[chamber]) as f:
                gj = json.load(f)
            district_ids = sorted(
                ft["properties"]["district"] for ft in gj["features"]
            )

        results = []
        total = len(district_ids)
        for i, did in enumerate(district_ids):
            print(f"\n[{i+1}/{total}] Analyzing {chamber} district {did}...")
            try:
                r = self.analyze_district(chamber, did)
                results.append(r)
            except Exception as e:
                print(f"  ERROR on district {did}: {e}")
        return results


# ── Text parsing helpers ──────────────────────────────────────────────────────

def _strip_bold(text: str) -> str:
    """Remove ** markdown bold markers that LLMs add to section headers."""
    return text.replace("**", "")

def _extract_section(text: str, start_marker: str, end_marker: str) -> str:
    """Extract text between two markers, stripping bold markdown artifacts."""
    clean = _strip_bold(text)
    try:
        start = clean.index(start_marker) + len(start_marker)
        try:
            end = clean.index(end_marker, start)
            return clean[start:end]
        except ValueError:
            return clean[start:]
    except ValueError:
        return ""

def _extract_line(text: str, marker: str) -> str:
    """Extract the rest of a line after a marker, stripping bold markdown artifacts."""
    for line in text.splitlines():
        stripped = _strip_bold(line)
        if marker in stripped:
            return stripped.split(marker, 1)[-1].strip()
    return ""


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    chamber    = sys.argv[1] if len(sys.argv) > 1 else "senate"
    district   = int(sys.argv[2]) if len(sys.argv) > 2 else 38

    print(f"\n{'='*60}")
    print(f"Narrative Crew: {chamber.upper()} District {district}")
    print('='*60)

    crew   = NarrativeCrew()
    result = crew.analyze_district(chamber, district)

    print(f"\n{'='*60}")
    print(f"RED FLAG: {result.red_flag_level} — {result.red_flag_reason}")
    print(f"\nNARRATIVE:\n{result.narrative}")
    print(f"\nADVOCATE POINTS:")
    for pt in result.advocate_points:
        print(f"  • {pt}")
    print(f"\nFAIR MAP NOTE: {result.fair_map_note}")
    print('='*60)