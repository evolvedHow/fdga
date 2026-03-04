#!/bin/bash
# ============================================================
# Fix script for fdga backend import errors
# Run from your project root: bash fix_backend_imports.sh
# ============================================================

echo "🔧 Fixing fdga backend package structure..."
echo ""

# Step 1: Create missing __init__.py files
echo "📦 Creating __init__.py files..."

touch backend/__init__.py
touch backend/tools/__init__.py
touch backend/agents/__init__.py
touch backend/crews/__init__.py
touch backend/routers/__init__.py

echo "   ✓ backend/__init__.py"
echo "   ✓ backend/tools/__init__.py"
echo "   ✓ backend/agents/__init__.py"
echo "   ✓ backend/crews/__init__.py"
echo "   ✓ backend/routers/__init__.py"
echo ""

# Step 2: Fix pyproject.toml — remove bogus 'backend' PyPI dependency
echo "🔧 Fixing pyproject.toml..."

if grep -q '"backend>=' pyproject.toml; then
    # Remove the line with backend>=
    sed -i '/"backend>=/d' pyproject.toml
    echo "   ✓ Removed bogus 'backend>=0.2.4.1' from pyproject.toml"
    echo "     (This was a PyPI package unrelated to your local backend/ folder)"
else
    echo "   ✓ pyproject.toml already clean (no bogus backend dependency)"
fi
echo ""

# Step 3: Check if llm_factory.py exists (agents.py imports it)
echo "🔍 Checking for llm_factory.py..."
if [ ! -f "backend/llm_factory.py" ]; then
    echo "   ⚠  Missing: backend/llm_factory.py — creating it now..."
    cat > backend/llm_factory.py << 'EOF'
"""
LLM Factory — returns the right LLM based on .env settings.
Supports: ollama (local), groq (free cloud), gemini (free cloud)
"""

import os
from dotenv import load_dotenv

load_dotenv()


def get_llm(temperature: float = 0.1):
    """
    Returns a LangChain-compatible LLM based on LLM_PROVIDER in .env.
    
    Set in your .env:
        LLM_PROVIDER=ollama      # local, free, private
        LLM_PROVIDER=groq        # fast, free tier 30 req/min
        LLM_PROVIDER=gemini      # free tier 1500 req/day
    """
    provider = os.getenv("LLM_PROVIDER", "ollama").lower()

    if provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(
            model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
            api_key=os.getenv("GROQ_API_KEY"),
            temperature=temperature,
        )

    elif provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=os.getenv("GEMINI_MODEL", "gemini-1.5-flash"),
            google_api_key=os.getenv("GEMINI_API_KEY"),
            temperature=temperature,
        )

    else:
        # Default: Ollama (local)
        from langchain_ollama import ChatOllama
        return ChatOllama(
            model=os.getenv("OLLAMA_MODEL", "llama3.2"),
            temperature=temperature,
        )
EOF
    echo "   ✓ Created backend/llm_factory.py"
else
    echo "   ✓ backend/llm_factory.py exists"
fi
echo ""

# Step 4: Check for .env file
echo "🔍 Checking .env..."
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "   ✓ Created .env from .env.example — edit it to set your LLM provider"
    else
        echo "   ⚠  No .env file found — creating minimal one..."
        cat > .env << 'EOF'
# LLM Provider: ollama | groq | gemini
LLM_PROVIDER=ollama
OLLAMA_MODEL=llama3.2

# Uncomment and fill in if using cloud providers:
# GROQ_API_KEY=your_key_here
# GEMINI_API_KEY=your_key_here

# Data directory (relative to project root)
GEOJSON_SOURCE_DIR=./fdga/data
DATA_DIR=./fdga/data
EOF
        echo "   ✓ Created minimal .env — edit to set your preferred LLM"
    fi
else
    echo "   ✓ .env exists"
fi
echo ""

# Step 5: Verify the fix works
echo "🧪 Verifying fix..."
python - << 'PYEOF'
import sys
from pathlib import Path
sys.path.insert(0, str(Path('.').absolute()))

try:
    from backend.tools.duckdb_tool import DistrictDataTool
    print("   ✓ backend.tools.duckdb_tool — OK")
except ImportError as e:
    print(f"   ✗ backend.tools.duckdb_tool — FAILED: {e}")

try:
    from backend.tools.chart_tool import ChartTool
    print("   ✓ backend.tools.chart_tool — OK")
except ImportError as e:
    print(f"   ✗ backend.tools.chart_tool — FAILED: {e}")

try:
    from backend.agents.agents import create_agents
    print("   ✓ backend.agents.agents — OK")
except ImportError as e:
    print(f"   ✗ backend.agents.agents — FAILED: {e}")

try:
    from backend.crews.analysis_crew import FairDistrictsGACrew
    print("   ✓ backend.crews.analysis_crew — OK")
except ImportError as e:
    print(f"   ✗ backend.crews.analysis_crew — FAILED: {e}")
PYEOF

echo ""
echo "============================================================"
echo "✅ Done! Now run:"
echo ""
echo "   python scripts/test_question.py --data-only"
echo ""
echo "If you get 'No data found', also run:"
echo "   python scripts/extract_geojson_to_csv.py"
echo "============================================================"