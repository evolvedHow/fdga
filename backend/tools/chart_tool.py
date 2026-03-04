"""
Chart Generation Tool for Fair Districts GA
============================================
Generates bar charts, comparison charts, and demographic breakdowns
as PNG images that can be sent via Telegram/WhatsApp or displayed on web.
"""

import os
import io
import base64
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend — works in servers with no display
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from pathlib import Path
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Literal, Optional


# ── Color scheme matching FDGA brand ──────────────────────────────────────────
FDGA_COLORS = {
    "bvap":       "#664296",   # Purple (matches map)
    "hvap":       "#a63603",   # Orange-red
    "avap":       "#006d2c",   # Green
    "bipoc_vap":  "#1a6f9e",   # Blue
    "partisan":   "#d62728",   # Red
    "neutral":    "#636363",
    "highlight":  "#c90000",   # FDGA highlight red
    "background": "#f7f7f7",
}

OUTPUT_DIR = Path("./data/charts")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ── Schema ────────────────────────────────────────────────────────────────────

class ChartInput(BaseModel):
    chart_type: Literal["bar", "comparison", "breakdown"] = Field(
        description="""
        Type of chart:
        - 'bar': Single metric across all districts (e.g., BVAP% by district)
        - 'comparison': Same metric across two map versions side-by-side
        - 'breakdown': Stacked breakdown of demographics for each district
        """
    )
    data_csv: str = Field(
        description="""
        CSV-formatted data string to plot. Must include a header row.
        Example:
          DISTRICT,bvap_pct,map_version
          1,45.2,enacted_2024
          2,28.1,enacted_2024
        """
    )
    title: str = Field(description="Chart title")
    x_column: str = Field(description="Column to use for X axis (usually 'DISTRICT')")
    y_column: str = Field(description="Column to use for Y axis (e.g., 'bvap_pct')")
    color_key: Optional[str] = Field(
        default="bvap",
        description="Color theme: bvap | hvap | avap | bipoc_vap | partisan | neutral"
    )
    y_label: Optional[str] = Field(default=None, description="Y axis label")
    threshold_line: Optional[float] = Field(
        default=None,
        description="Draw a horizontal threshold line (e.g., 50.0 for majority-minority)"
    )
    compare_column: Optional[str] = Field(
        default=None,
        description="For 'comparison' charts: the second Y column to compare against"
    )
    filename: Optional[str] = Field(
        default="chart.png",
        description="Output filename (saved to data/charts/)"
    )


# ── Tool ──────────────────────────────────────────────────────────────────────

class ChartTool(BaseTool):
    """Generate charts from redistricting data and save as PNG images."""
    name: str = "generate_chart"
    description: str = """
    Generate a chart (bar chart, comparison chart, or demographic breakdown)
    from redistricting data. Returns the path to the saved PNG image.
    Use this after querying data with query_district_data.
    """
    args_schema: type[BaseModel] = ChartInput

    def _run(
        self,
        chart_type: str,
        data_csv: str,
        title: str,
        x_column: str,
        y_column: str,
        color_key: str = "bvap",
        y_label: Optional[str] = None,
        threshold_line: Optional[float] = None,
        compare_column: Optional[str] = None,
        filename: str = "chart.png",
    ) -> str:
        try:
            # Parse the CSV data
            df = pd.read_csv(io.StringIO(data_csv))

            if x_column not in df.columns:
                return f"Error: column '{x_column}' not found. Available: {df.columns.tolist()}"
            if y_column not in df.columns:
                return f"Error: column '{y_column}' not found. Available: {df.columns.tolist()}"

            # Sort by district number if possible
            try:
                df[x_column] = df[x_column].astype(str)
                df = df.sort_values(
                    x_column,
                    key=lambda x: pd.to_numeric(x, errors='coerce').fillna(0)
                )
            except Exception:
                pass

            color = FDGA_COLORS.get(color_key, FDGA_COLORS["neutral"])
            output_path = OUTPUT_DIR / filename

            if chart_type == "bar":
                self._make_bar_chart(df, x_column, y_column, title, color,
                                     y_label, threshold_line, output_path)
            elif chart_type == "comparison":
                self._make_comparison_chart(df, x_column, y_column, compare_column,
                                            title, color, y_label, threshold_line, output_path)
            elif chart_type == "breakdown":
                self._make_breakdown_chart(df, x_column, title, output_path)

            return str(output_path.absolute())

        except Exception as e:
            return f"Chart generation error: {str(e)}"

    def _make_bar_chart(self, df, x_col, y_col, title, color, y_label, threshold, output_path):
        """Simple bar chart — one metric, one map version."""
        fig, ax = plt.subplots(figsize=(max(10, len(df) * 0.35), 6))
        fig.patch.set_facecolor(FDGA_COLORS["background"])
        ax.set_facecolor(FDGA_COLORS["background"])

        bars = ax.bar(range(len(df)), df[y_col], color=color, alpha=0.85, width=0.7)

        # Highlight bars above threshold
        if threshold is not None:
            for i, (bar, val) in enumerate(zip(bars, df[y_col])):
                if val >= threshold:
                    bar.set_color(FDGA_COLORS["highlight"])
                    bar.set_alpha(0.95)
            ax.axhline(y=threshold, color='black', linestyle='--',
                       linewidth=1.5, label=f'{threshold}% threshold')
            ax.legend(fontsize=10)

        # Labels
        ax.set_xticks(range(len(df)))
        ax.set_xticklabels(df[x_col], rotation=90, fontsize=8)
        ax.set_xlabel("District", fontsize=12)
        ax.set_ylabel(y_label or y_col, fontsize=12)
        ax.set_title(title, fontsize=14, fontweight='bold', pad=15)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.1f}%"))
        ax.grid(axis='y', alpha=0.3)

        # Value labels on top of each bar (if not too many bars)
        if len(df) <= 30:
            for bar, val in zip(bars, df[y_col]):
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                        f"{val:.1f}", ha='center', va='bottom', fontsize=7, rotation=90)

        # FDGA branding
        fig.text(0.99, 0.01, 'fairdistrictsga.org', ha='right', va='bottom',
                 fontsize=8, color='gray', style='italic')

        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight',
                    facecolor=FDGA_COLORS["background"])
        plt.close()

    def _make_comparison_chart(self, df, x_col, y_col1, y_col2, title,
                                color, y_label, threshold, output_path):
        """Side-by-side bars comparing two map versions."""
        if y_col2 is None or y_col2 not in df.columns:
            return self._make_bar_chart(df, x_col, y_col1, title, color,
                                        y_label, threshold, output_path)

        fig, ax = plt.subplots(figsize=(max(12, len(df) * 0.5), 6))
        fig.patch.set_facecolor(FDGA_COLORS["background"])
        ax.set_facecolor(FDGA_COLORS["background"])

        x = range(len(df))
        width = 0.35

        bars1 = ax.bar([i - width/2 for i in x], df[y_col1],
                       width, label=y_col1, color=color, alpha=0.75)
        bars2 = ax.bar([i + width/2 for i in x], df[y_col2],
                       width, label=y_col2, color=FDGA_COLORS["neutral"], alpha=0.75)

        if threshold is not None:
            ax.axhline(y=threshold, color='black', linestyle='--',
                       linewidth=1.5, label=f'{threshold}% threshold')

        ax.set_xticks(list(x))
        ax.set_xticklabels(df[x_col], rotation=90, fontsize=8)
        ax.set_xlabel("District", fontsize=12)
        ax.set_ylabel(y_label or "Value", fontsize=12)
        ax.set_title(title, fontsize=14, fontweight='bold', pad=15)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.1f}%"))
        ax.legend(fontsize=10)
        ax.grid(axis='y', alpha=0.3)

        fig.text(0.99, 0.01, 'fairdistrictsga.org', ha='right', va='bottom',
                 fontsize=8, color='gray', style='italic')

        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight',
                    facecolor=FDGA_COLORS["background"])
        plt.close()

    def _make_breakdown_chart(self, df, x_col, title, output_path):
        """Stacked bar showing demographic breakdown by district."""
        demo_cols = [c for c in ['bvap_pct', 'hvap_pct', 'avap_pct', 'other_pct']
                     if c in df.columns]
        if not demo_cols:
            # Fallback if column names are different
            demo_cols = [c for c in df.columns if c != x_col][:4]

        colors = [FDGA_COLORS["bvap"], FDGA_COLORS["hvap"],
                  FDGA_COLORS["avap"], FDGA_COLORS["neutral"]]

        fig, ax = plt.subplots(figsize=(max(10, len(df) * 0.4), 6))
        fig.patch.set_facecolor(FDGA_COLORS["background"])
        ax.set_facecolor(FDGA_COLORS["background"])

        bottom = [0] * len(df)
        for col, color in zip(demo_cols, colors):
            if col in df.columns:
                ax.bar(range(len(df)), df[col], bottom=bottom, label=col,
                       color=color, alpha=0.85, width=0.7)
                bottom = [b + v for b, v in zip(bottom, df[col])]

        ax.set_xticks(range(len(df)))
        ax.set_xticklabels(df[x_col], rotation=90, fontsize=8)
        ax.set_xlabel("District", fontsize=12)
        ax.set_ylabel("% of Voting Age Population", fontsize=12)
        ax.set_title(title, fontsize=14, fontweight='bold', pad=15)
        ax.legend(loc='upper right', fontsize=9)
        ax.grid(axis='y', alpha=0.3)

        fig.text(0.99, 0.01, 'fairdistrictsga.org', ha='right', va='bottom',
                 fontsize=8, color='gray', style='italic')

        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight',
                    facecolor=FDGA_COLORS["background"])
        plt.close()


# ── Quick test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tool = ChartTool()
    test_csv = """DISTRICT,bvap_pct,map_version
1,45.2,enacted_2024
2,28.1,enacted_2024
3,62.5,enacted_2024
4,18.3,enacted_2024
5,55.0,enacted_2024
6,33.7,enacted_2024"""

    result = tool._run(
        chart_type="bar",
        data_csv=test_csv,
        title="Black Voting Age Population % by Senate District (2024)",
        x_column="DISTRICT",
        y_column="bvap_pct",
        color_key="bvap",
        y_label="BVAP %",
        threshold_line=50.0,
        filename="test_bvap_chart.png"
    )
    print(f"Chart saved to: {result}")
