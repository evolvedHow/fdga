"""
fetch_rdh_data.py — Download Georgia Data from Redistricting Data Hub
======================================================================
RDH requires a free account. This script handles authentication
and downloads the key Georgia datasets automatically.

Setup:
    1. Register at https://redistrictingdatahub.org/
    2. Add to .env:
         RDH_USERNAME=your@email.com
         RDH_PASSWORD=yourpassword

Usage:
    python scripts/fetch_rdh_data.py --list          # show available GA datasets
    python scripts/fetch_rdh_data.py --download all  # download all key datasets
    python scripts/fetch_rdh_data.py --download pl   # just PL 94-171 census data
    python scripts/fetch_rdh_data.py --download boundaries  # just shapefiles
    python scripts/fetch_rdh_data.py --download elections   # just election results

After downloading, run:
    python scripts/ingest_to_parquet.py geojson
"""

import os
import sys
import json
import time
import zipfile
import argparse
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR  = Path(__file__).parent.parent
RAW_DIR   = BASE_DIR / "data" / "raw" / "rdh"
RAW_DIR.mkdir(parents=True, exist_ok=True)

RDH_API_BASE = "https://redistrictingdatahub.org/wp-json/download/v1"
RDH_LOGIN    = "https://redistrictingdatahub.org/wp-login.php"

# ── Key Georgia dataset slugs on RDH ──────────────────────────────────────────
# These are the most relevant datasets for Fair Districts GA's work.
# Find dataset slugs by browsing: https://redistrictingdatahub.org/state/georgia/
GEORGIA_DATASETS = {
    "pl": {
        "description": "2020 Census PL 94-171 Redistricting Data — Georgia (block level)",
        "slug": "2020-census-pl-94171-georgia",
        "notes": "Core demographic data: total pop, VAP, BVAP, HVAP, AVAP by census block",
        "priority": "HIGH",
    },
    "senate_2021": {
        "description": "Georgia State Senate Districts 2021 (enacted)",
        "slug": "2021-georgia-state-senate-districts-pl-94171",
        "notes": "Demographics aggregated to 2021 enacted senate districts",
        "priority": "HIGH",
    },
    "senate_2024": {
        "description": "Georgia State Senate Districts 2024 (remedy)",
        "slug": "2024-georgia-state-senate-districts-pl-94171",
        "notes": "Demographics aggregated to 2024 court-ordered remedy districts",
        "priority": "HIGH",
    },
    "house_2021": {
        "description": "Georgia State House Districts 2021 (enacted)",
        "slug": "2021-georgia-state-house-districts-pl-94171",
        "notes": "Demographics aggregated to 2021 enacted house districts",
        "priority": "HIGH",
    },
    "house_2024": {
        "description": "Georgia State House Districts 2024 (remedy)",
        "slug": "2024-georgia-state-house-districts-pl-94171",
        "notes": "Demographics aggregated to 2024 court-ordered remedy districts",
        "priority": "HIGH",
    },
    "congress_2021": {
        "description": "Georgia Congressional Districts 2021 (enacted)",
        "slug": "2021-georgia-congressional-districts-pl-94171",
        "notes": "Demographics aggregated to 2021 enacted congressional districts",
        "priority": "HIGH",
    },
    "elections_2020": {
        "description": "Georgia 2020 Election Results with Precinct Boundaries",
        "slug": "2020-georgia-presidential-election-results",
        "notes": "Precinct-level presidential results merged with boundaries",
        "priority": "HIGH",
    },
    "elections_2022": {
        "description": "Georgia 2022 Election Results",
        "slug": "2022-georgia-election-results",
        "notes": "Statewide election results for partisan lean calculation",
        "priority": "MEDIUM",
    },
    "counties": {
        "description": "Georgia County Boundaries 2020",
        "slug": "2020-georgia-county-boundaries",
        "notes": "County boundary shapefile for map overlay",
        "priority": "MEDIUM",
    },
    "cvap": {
        "description": "Citizen Voting Age Population — Georgia",
        "slug": "georgia-cvap-2019",
        "notes": "CVAP data for VRA Section 2 analysis",
        "priority": "MEDIUM",
    },
}


# ── RDH Authentication ─────────────────────────────────────────────────────────

class RDHClient:
    """HTTP client for Redistricting Data Hub."""

    def __init__(self):
        self.username = os.getenv("RDH_USERNAME")
        self.password = os.getenv("RDH_PASSWORD")
        self.session  = requests.Session()
        self.session.headers.update({
            "User-Agent": "FairDistrictsGA-DataPipeline/1.0 (fairdistrictsga.org)"
        })
        self._logged_in = False

    def login(self) -> bool:
        """Log in to RDH to get download access."""
        if not self.username or not self.password:
            print("❌ RDH credentials missing. Add to .env:")
            print("   RDH_USERNAME=your@email.com")
            print("   RDH_PASSWORD=yourpassword")
            print("\n   Register free at: https://redistrictingdatahub.org/")
            return False

        print(f"  Logging in as: {self.username}")
        try:
            resp = self.session.post(RDH_LOGIN, data={
                "log":         self.username,
                "pwd":         self.password,
                "wp-submit":   "Log In",
                "redirect_to": "https://redistrictingdatahub.org/",
                "testcookie":  "1",
            }, allow_redirects=True, timeout=30)

            if "dashboard" in resp.url or resp.status_code == 200:
                self._logged_in = True
                print("  ✓ Logged in")
                return True
            else:
                print(f"  ❌ Login failed (status {resp.status_code})")
                return False
        except Exception as e:
            print(f"  ❌ Login error: {e}")
            return False

    def download_dataset(self, slug: str, output_dir: Path) -> Path | None:
        """Download a dataset by slug. Returns path to extracted directory."""
        if not self._logged_in and not self.login():
            return None

        # Try the RDH download API
        download_url = f"https://redistrictingdatahub.org/dataset/{slug}/"
        print(f"  Fetching: {download_url}")

        try:
            # Get dataset page to find actual download link
            resp = self.session.get(download_url, timeout=30)
            if resp.status_code != 200:
                print(f"  ⚠ Dataset page returned {resp.status_code} — slug may be wrong")
                return None

            # Look for download link in page
            # RDH uses a specific download button pattern
            if "download" not in resp.text.lower():
                print(f"  ⚠ No download link found on page — may need API access")
                print(f"    Try manually downloading from: {download_url}")
                return None

            # Find zip download URL (pattern varies, this is approximate)
            import re
            zip_urls = re.findall(
                r'href="(https://[^"]*redistrictingdatahub[^"]*\.zip)"',
                resp.text
            )
            if not zip_urls:
                print(f"  ⚠ No .zip found — dataset may require API access tier")
                print(f"    Manual download: {download_url}")
                return None

            zip_url = zip_urls[0]
            return self._download_zip(zip_url, slug, output_dir)

        except Exception as e:
            print(f"  ❌ Error: {e}")
            return None

    def _download_zip(self, url: str, name: str, output_dir: Path) -> Path | None:
        """Download and extract a zip file."""
        zip_path = output_dir / f"{name}.zip"
        extract_path = output_dir / name

        if extract_path.exists():
            print(f"  ✓ Already downloaded: {name}/")
            return extract_path

        print(f"  Downloading: {url}")
        try:
            resp = self.session.get(url, stream=True, timeout=120)
            resp.raise_for_status()

            total = int(resp.headers.get("content-length", 0))
            downloaded = 0

            with open(zip_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = downloaded / total * 100
                        print(f"    {pct:.0f}%", end="\r")

            print(f"  ✓ Downloaded {downloaded/1024/1024:.1f} MB")

            # Extract
            extract_path.mkdir(exist_ok=True)
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(extract_path)
            zip_path.unlink()  # remove zip, keep extracted files
            print(f"  ✓ Extracted to: {extract_path}/")
            return extract_path

        except Exception as e:
            print(f"  ❌ Download failed: {e}")
            if zip_path.exists():
                zip_path.unlink()
            return None


# ── Dataset processing ─────────────────────────────────────────────────────────

def process_rdh_district_csv(csv_path: Path, chamber: str, map_version: str) -> None:
    """
    Process a downloaded RDH district-level CSV and add to parquet pipeline.
    RDH district files already have demographics aggregated per district.
    """
    import pandas as pd
    sys.path.insert(0, str(BASE_DIR))
    from scripts.ingest_to_parquet import run_analyst_pipeline
    from scripts.schema import RDH_COLUMN_MAP

    print(f"\n  Processing RDH district CSV: {csv_path.name}")
    df = pd.read_csv(csv_path)

    # Rename RDH columns to canonical names
    rename_map = {old: new for old, new in RDH_COLUMN_MAP.items() if old in df.columns}
    df = df.rename(columns=rename_map)
    print(f"  Columns after rename: {df.columns.tolist()}")

    # Save normalized version for analyst pipeline
    normalized_path = RAW_DIR / f"normalized_{csv_path.name}"
    df.to_csv(normalized_path, index=False)

    run_analyst_pipeline(normalized_path, chamber, map_version)


def list_datasets():
    """Print available Georgia datasets."""
    print("\n📊 Key Georgia Datasets on Redistricting Data Hub")
    print("="*60)
    for key, ds in GEORGIA_DATASETS.items():
        priority_icon = "🔴" if ds["priority"] == "HIGH" else "🟡"
        print(f"\n{priority_icon} [{key}] {ds['description']}")
        print(f"   Slug: {ds['slug']}")
        print(f"   Notes: {ds['notes']}")
    print("\n" + "="*60)
    print("Register at: https://redistrictingdatahub.org/")
    print("Then add RDH_USERNAME and RDH_PASSWORD to your .env")


def download_datasets(target: str = "all"):
    """Download one or all datasets."""
    client = RDHClient()

    if target == "all":
        to_download = list(GEORGIA_DATASETS.keys())
    elif target in GEORGIA_DATASETS:
        to_download = [target]
    else:
        # Filter by priority
        to_download = [k for k, v in GEORGIA_DATASETS.items() 
                      if v["priority"] == "HIGH"]

    print(f"\nDownloading {len(to_download)} datasets to: {RAW_DIR}")

    for key in to_download:
        ds = GEORGIA_DATASETS[key]
        print(f"\n{'─'*50}")
        print(f"Dataset: {ds['description']}")
        result = client.download_dataset(ds["slug"], RAW_DIR)
        if result:
            print(f"  ✓ Success: {result}")
        else:
            print(f"  ℹ Manual download: https://redistrictingdatahub.org/dataset/{ds['slug']}/")
        time.sleep(1)  # Be polite to their servers

    print(f"\n{'='*50}")
    print("Downloads complete. Next steps:")
    print("  1. Review downloaded files in data/raw/rdh/")
    print("  2. Run: python scripts/ingest_to_parquet.py geojson")
    print("  3. For RDH CSV files, run: python scripts/ingest_to_parquet.py analyst --file <path> --chamber <chamber> --map-version <version>")


# ── CLI ────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Download Georgia redistricting data from Redistricting Data Hub"
    )
    parser.add_argument("--list",     action="store_true",  help="List available datasets")
    parser.add_argument("--download", metavar="TARGET",     help="Download datasets: all | high | <key>")

    args = parser.parse_args()

    if args.list:
        list_datasets()
    elif args.download:
        download_datasets(args.download)
    else:
        list_datasets()
        print("\nRun with --download all to download all high-priority datasets")


if __name__ == "__main__":
    main()