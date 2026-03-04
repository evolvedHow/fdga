"""
Test Script — Ask a Question from the Command Line
====================================================
Usage:
    python scripts/test_question.py "Which Senate districts have BVAP over 50%?"
    python scripts/test_question.py --quick "What is the BVAP of Senate district 5?"
    python scripts/test_question.py --data-only  (just test DuckDB, no AI)
"""

import sys
import asyncio
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_data_layer():
    """Test that DuckDB can query the data without any AI."""
    print("=" * 60)
    print("Testing Data Layer (DuckDB only — no AI needed)")
    print("=" * 60)


    from backend.tools.duckdb_tool import list_available_data, quick_query

    print("\n📁 Available data:")
    import json
    data_info = list_available_data()
    print(json.dumps(data_info, indent=2))

    # Test a simple query
    print("\n📊 Sample query — Senate districts by BVAP (enacted_2024):")
    try:
        df = quick_query("""
            SELECT DISTRICT,
                   ROUND(pct_bvap * 100, 1) as bvap_pct,
                   ROUND(partisan_lean * 100, 1) as partisan_pct
            FROM senate_districts
            WHERE map_version = 'enacted_2024'
            ORDER BY pct_bvap DESC
            LIMIT 10
        """)
        print(df.to_string(index=False))
        print("\n✅ Data layer working correctly!")
    except Exception as e:
        print(f"❌ Query failed: {e}")
        print("\nTry running: python scripts/generate_sample_data.py")
        return False
    return True


async def test_ai_question(question: str, quick: bool = False):
    """Test the full AI pipeline with a question."""
    print("=" * 60)
    print(f"{'Quick' if quick else 'Full'} AI Analysis")
    print(f"Question: {question}")
    print("=" * 60)
    print("(This may take 10-40 seconds depending on your model...)\n")

    from backend.crews.analysis_crew import FairDistrictsGACrew

    crew = FairDistrictsGACrew()

    if quick:
        result = crew.quick_answer(question)
    else:
        result = crew.full_analysis(question)

    print("\n" + "=" * 60)
    print("📝 ANSWER:")
    print("=" * 60)
    print(result.answer)

    if result.has_chart:
        print(f"\n📊 Chart saved to: {result.chart_path}")
    
    print("\n" + "=" * 60)
    print("🔍 RAW DATA:")
    print("=" * 60)
    print(result.data_summary[:500] + "..." if len(result.data_summary) > 500
          else result.data_summary)


def main():
    parser = argparse.ArgumentParser(description="Test the Fair Districts GA AI backend")
    parser.add_argument("question", nargs="?",
                        default="Which Georgia Senate districts in the 2024 enacted map have more than 50% Black voting age population?",
                        help="Question to ask")
    parser.add_argument("--quick", action="store_true",
                        help="Use quick single-agent mode (faster, no chart)")
    parser.add_argument("--data-only", action="store_true",
                        help="Test DuckDB data layer only (no AI)")
    args = parser.parse_args()

    if args.data_only:
        test_data_layer()
    else:
        asyncio.run(test_ai_question(args.question, quick=args.quick))


if __name__ == "__main__":
    main()
