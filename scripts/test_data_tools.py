"""
Tests for the DuckDB data layer.
Run with: pytest tests/test_data_tools.py -v
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(scope="module", autouse=True)
def setup_sample_data():
    """Generate sample data before running tests."""
    data_dir = Path("./data")
    # Only generate if files don't exist
    if not (data_dir / "senate_districts.csv").exists():
        import subprocess
        result = subprocess.run(
            ["python", "scripts/generate_sample_data.py"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            pytest.skip(f"Could not generate sample data: {result.stderr}")


class TestDuckDBTool:
    def setup_method(self):
        from backend.tools.duckdb_tool import DistrictDataTool
        self.tool = DistrictDataTool()

    def test_basic_query(self):
        result = self.tool._run(
            sql="SELECT COUNT(*) as n FROM senate_districts",
        )
        assert "n" in result
        assert "Query returned" in result

    def test_filter_by_map_version(self):
        result = self.tool._run(
            sql="""
            SELECT DISTRICT, pct_bvap 
            FROM senate_districts 
            WHERE map_version = 'enacted_2024'
            LIMIT 5
            """,
        )
        assert "DISTRICT" in result
        assert "Error" not in result

    def test_majority_minority_count(self):
        result = self.tool._run(
            sql="""
            SELECT COUNT(*) as majority_minority
            FROM senate_districts
            WHERE map_version = 'enacted_2024'
            AND pct_bipoc_vap > 0.5
            """
        )
        assert "majority_minority" in result

    def test_comparison_query(self):
        result = self.tool._run(
            sql="""
            SELECT map_version,
                   AVG(pct_bvap) as avg_bvap,
                   COUNT(*) as districts
            FROM senate_districts
            GROUP BY map_version
            ORDER BY map_version
            """
        )
        assert "map_version" in result
        assert "avg_bvap" in result

    def test_rejects_non_select(self):
        result = self.tool._run(sql="DROP TABLE senate_districts")
        assert "ERROR" in result

    def test_house_districts(self):
        result = self.tool._run(
            sql="SELECT COUNT(*) as n FROM house_districts WHERE map_version = 'enacted_2024'"
        )
        assert "Error" not in result


class TestChartTool:
    def setup_method(self):
        from backend.tools.chart_tool import ChartTool
        self.tool = ChartTool()

    def test_bar_chart(self, tmp_path):
        test_csv = """DISTRICT,bvap_pct
1,45.2
2,28.1
3,62.5
4,18.3
5,55.0"""
        result = self.tool._run(
            chart_type="bar",
            data_csv=test_csv,
            title="Test BVAP Chart",
            x_column="DISTRICT",
            y_column="bvap_pct",
            threshold_line=50.0,
            filename="test_chart.png",
        )
        assert ".png" in result
        assert "error" not in result.lower()

    def test_missing_column_error(self):
        result = self.tool._run(
            chart_type="bar",
            data_csv="DISTRICT,bvap_pct\n1,45.2",
            title="Test",
            x_column="DISTRICT",
            y_column="nonexistent_column",
            filename="test_error.png",
        )
        assert "Error" in result


class TestDataExtraction:
    def test_sample_csvs_exist(self):
        for chamber in ["senate", "house", "congress"]:
            path = Path(f"./data/{chamber}_districts.csv")
            assert path.exists(), f"Missing: {path}"

    def test_csv_has_required_columns(self):
        import pandas as pd
        df = pd.read_csv("./data/senate_districts.csv")
        required = ["DISTRICT", "map_version", "pct_bvap"]
        for col in required:
            assert col in df.columns, f"Missing column: {col}"

    def test_pct_columns_in_range(self):
        import pandas as pd
        df = pd.read_csv("./data/senate_districts.csv")
        for col in ["pct_bvap", "pct_hvap", "pct_avap"]:
            if col in df.columns:
                assert df[col].max() <= 1.01, f"{col} has values > 1.0"
                assert df[col].min() >= -0.01, f"{col} has negative values"
