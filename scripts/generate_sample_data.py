"""
Generate Sample Data for Testing
==================================
Creates realistic-looking fake district data so you can test
the AI backend even before connecting your real GeoJSON files.

Run:
    python scripts/generate_sample_data.py
"""

import pandas as pd
import numpy as np
from pathlib import Path

np.random.seed(42)  # Reproducible fake data


def generate_chamber_data(chamber: str, n_districts: int) -> pd.DataFrame:
    """Generate fake but realistic district demographic data."""

    map_versions = ["enacted_2021", "enacted_2024", "proposed_dem", "proposed_rep"]
    rows = []

    for version in map_versions:
        for district_num in range(1, n_districts + 1):
            # Simulate geographic clustering — some districts are in high-minority areas
            base_bvap = np.clip(np.random.beta(2, 5) + (0.3 if district_num % 7 == 0 else 0), 0, 1)
            base_hvap = np.clip(np.random.beta(1.5, 8), 0, 0.4)
            base_avap = np.clip(np.random.beta(1, 12), 0, 0.2)

            # Ensure percentages don't exceed 1.0 combined
            total_minority = base_bvap + base_hvap + base_avap
            if total_minority > 0.95:
                scale = 0.95 / total_minority
                base_bvap *= scale
                base_hvap *= scale
                base_avap *= scale

            bipoc_vap = min(base_bvap + base_hvap + base_avap, 1.0)

            # Partisan lean correlated with minority population
            partisan = np.clip(
                (bipoc_vap - 0.35) * 2 + np.random.normal(0, 0.15),
                -1, 1
            )

            # Population (Senate ~200k, House ~57k, Congress ~764k)
            pop_by_chamber = {"senate": 200000, "house": 57000, "congress": 764000}
            base_pop = pop_by_chamber.get(chamber, 100000)
            total_pop = int(np.random.normal(base_pop, base_pop * 0.05))
            total_vap = int(total_pop * 0.77)

            rows.append({
                "DISTRICT": str(district_num),
                "map_version": version,
                "chamber": chamber,
                "total_pop": total_pop,
                "total_vap": total_vap,
                "bvap": int(total_vap * base_bvap),
                "hvap": int(total_vap * base_hvap),
                "avap": int(total_vap * base_avap),
                "bipoc_vap": int(total_vap * bipoc_vap),
                "pct_bvap": round(base_bvap, 4),
                "pct_hvap": round(base_hvap, 4),
                "pct_avap": round(base_avap, 4),
                "pct_bipoc_vap": round(bipoc_vap, 4),
                "partisan_lean": round(partisan, 4),
            })

    return pd.DataFrame(rows)


def main():
    output_dir = Path("./data")
    output_dir.mkdir(parents=True, exist_ok=True)
    samples_dir = output_dir / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)

    chambers = {
        "senate":   56,   # Georgia has 56 Senate districts
        "house":    180,  # Georgia has 180 House districts
        "congress": 14,   # Georgia has 14 Congressional districts
    }

    for chamber, n_districts in chambers.items():
        df = generate_chamber_data(chamber, n_districts)

        # Full file
        path = output_dir / f"{chamber}_districts.csv"
        df.to_csv(path, index=False)
        print(f"✓ {path.name}: {len(df)} rows "
              f"({n_districts} districts × {len(df)//n_districts} map versions)")

        # Sample
        sample = df[df["map_version"] == "enacted_2024"].head(20)
        sample_path = samples_dir / f"{chamber}_sample.csv"
        sample.to_csv(sample_path, index=False)

    print(f"\n✅ Sample data generated in: {output_dir.absolute()}")
    print("   Replace these with real data by running: python scripts/extract_geojson_to_csv.py")


if __name__ == "__main__":
    main()
