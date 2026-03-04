"""
Analysis Crew — Assembles Agents into a Working Crew
======================================================
The crew takes a user question and coordinates the three agents
to produce a complete response: data + chart + plain-English explanation.

Two crew modes:
  full_analysis()  — All three agents, best for complex questions (~20-40s)
  quick_answer()   — Data analyst only, best for simple lookups (~5-10s)
"""

import os
from dataclasses import dataclass
from pathlib import Path
from crewai import Crew, Task, Process
from backend.agents.agents import create_agents


# ── Result data class ─────────────────────────────────────────────────────────

@dataclass
class AnalysisResult:
    """Structured result from the crew."""
    answer: str          # Plain-English summary from policy writer
    data_summary: str    # Raw data from analyst
    chart_path: str      # Path to chart PNG (empty string if no chart)
    question: str        # Original user question
    
    @property
    def has_chart(self) -> bool:
        return bool(self.chart_path) and Path(self.chart_path).exists()

    def to_dict(self) -> dict:
        return {
            "answer": self.answer,
            "data_summary": self.data_summary,
            "chart_path": self.chart_path,
            "has_chart": self.has_chart,
            "question": self.question,
        }


# ── Crew builder ──────────────────────────────────────────────────────────────

class FairDistrictsGACrew:
    """
    Main crew for answering redistricting questions.
    
    Usage:
        crew = FairDistrictsGACrew()
        result = crew.full_analysis("Which districts have BVAP > 50%?")
        print(result.answer)
        if result.has_chart:
            # Send result.chart_path as image
    """

    def __init__(self):
        print("🚀 Initializing Fair Districts GA AI Crew...")
        self.data_analyst, self.chart_maker, self.policy_writer = create_agents()
        print("✓ Agents ready")

    def full_analysis(self, question: str) -> AnalysisResult:
        """
        Full 3-agent analysis: data → chart → plain-English explanation.
        Best for complex analytical questions.
        Takes 20-40 seconds depending on model and complexity.
        """
        print(f"\n📊 Starting full analysis for: '{question}'")

        # ── Task 1: Data Analyst queries the data ──────────────────────────────
        analyze_task = Task(
            description=f"""
            Answer this question using the district data: {question}
            
            Steps:
            1. Write a SQL query for the relevant table(s) 
            2. Execute it using the query_district_data tool
            3. If the query fails, fix it and try again (max 3 attempts)
            4. Return your findings as CSV-formatted text so the chart maker can use it
            5. Also note: what map version(s) did you query? How many districts?
            
            Return format:
            DATA:
            <CSV of results here>
            
            FINDINGS:
            <2-3 bullet points summarizing what you found>
            """,
            expected_output="CSV-formatted data plus a bullet-point summary of findings",
            agent=self.data_analyst,
        )

        # ── Task 2: Chart Maker visualizes the data ────────────────────────────
        chart_task = Task(
            description=f"""
            Create a chart visualizing the data analyst's findings for: {question}
            
            Steps:
            1. Extract the CSV data from the analyst's output (the DATA: section)
            2. Determine the best chart type:
               - Single metric comparison → 'bar' chart
               - Two map versions side by side → 'comparison' chart
               - Multiple demographics per district → 'breakdown' chart
            3. Generate the chart using the generate_chart tool
            4. Return the file path to the saved PNG
            
            IMPORTANT: If pct_* columns are 0.0-1.0 scale, multiply by 100 
            before passing to chart (or rename column with _pct suffix).
            Include a 50% threshold line for any majority-minority analysis.
            
            If there are fewer than 3 data points, skip charting and say 'No chart needed'.
            """,
            expected_output="File path to the saved chart PNG, or 'No chart needed'",
            agent=self.chart_maker,
            context=[analyze_task],  # Gets analyst's output as input
        )

        # ── Task 3: Policy Writer synthesizes for the audience ─────────────────
        explain_task = Task(
            description=f"""
            Write a clear, accessible explanation for this question: {question}
            
            Use the data analyst's findings and note if a chart was created.
            
            Format your response as:
            
            **Summary:** (1-2 sentences — the headline finding)
            
            **Details:** (2-3 sentences with specific numbers)
            
            **What this means:** (1-2 sentences connecting to real communities and VRA context)
            
            Keep total response under 300 words (for Telegram/chat compatibility).
            Use plain language. Spell out acronyms on first use.
            """,
            expected_output="A 3-paragraph plain-English explanation under 300 words",
            agent=self.policy_writer,
            context=[analyze_task, chart_task],
        )

        # ── Assemble and run the crew ──────────────────────────────────────────
        crew = Crew(
            agents=[self.data_analyst, self.chart_maker, self.policy_writer],
            tasks=[analyze_task, chart_task, explain_task],
            process=Process.sequential,  # Run tasks in order
            verbose=True,
        )

        crew_output = crew.kickoff()

        # Extract chart path from chart task output
        chart_path = ""
        chart_output = str(chart_task.output or "")
        for line in chart_output.split("\n"):
            if ".png" in line.lower() and "/" in line:
                # Extract the file path
                parts = line.strip().split()
                for part in parts:
                    if ".png" in part:
                        chart_path = part.strip(".,\"'")
                        break

        return AnalysisResult(
            answer=str(explain_task.output or crew_output),
            data_summary=str(analyze_task.output or ""),
            chart_path=chart_path,
            question=question,
        )

    def quick_answer(self, question: str) -> AnalysisResult:
        """
        Single-agent fast answer — data analyst only, no chart.
        Best for simple factual questions.
        Takes 5-10 seconds.
        """
        print(f"\n⚡ Quick answer for: '{question}'")

        quick_task = Task(
            description=f"""
            Answer this question concisely: {question}
            
            Query the appropriate district data table, get the answer,
            and respond in 2-3 sentences with the specific numbers.
            """,
            expected_output="2-3 sentence answer with specific numbers",
            agent=self.data_analyst,
        )

        crew = Crew(
            agents=[self.data_analyst],
            tasks=[quick_task],
            process=Process.sequential,
            verbose=False,
        )

        crew.kickoff()

        return AnalysisResult(
            answer=str(quick_task.output or ""),
            data_summary=str(quick_task.output or ""),
            chart_path="",
            question=question,
        )


# ── Simple query classifier ────────────────────────────────────────────────────

def is_complex_question(question: str) -> bool:
    """
    Heuristic: decide if this needs full crew or just quick answer.
    Complex = comparison, visualization, multi-step analysis.
    """
    complex_keywords = [
        "compare", "comparison", "chart", "graph", "show me", "visualize",
        "difference", "changed", "vs", "versus", "all districts", "breakdown",
        "analyze", "analysis", "explain", "which districts", "how many",
    ]
    q_lower = question.lower()
    return any(kw in q_lower for kw in complex_keywords)


async def answer_question(question: str) -> AnalysisResult:
    """
    Main entry point — routes to quick or full analysis automatically.
    Call this from the FastAPI endpoints and Telegram bot.
    """
    crew = FairDistrictsGACrew()

    if is_complex_question(question):
        return crew.full_analysis(question)
    else:
        return crew.quick_answer(question)


# ── CLI test ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import asyncio
    import sys

    question = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else \
        "Which Georgia Senate districts in the 2024 enacted map have more than 50% Black voting age population?"

    print(f"\n{'='*60}")
    print(f"Question: {question}")
    print('='*60)

    result = asyncio.run(answer_question(question))

    print(f"\n{'='*60}")
    print("ANSWER:")
    print(result.answer)
    if result.has_chart:
        print(f"\nChart saved: {result.chart_path}")
    print('='*60)
