"""
LLM Factory — Forces CrewAI to use Ollama (or other providers)
===============================================================
CrewAI ignores LangChain LLMs passed to agents in newer versions.
It has its own LLM class that must be used instead.
"""

import os
from dotenv import load_dotenv

load_dotenv()


def get_llm(temperature: float = 0.1):
    """
    Return a CrewAI-native LLM object (not LangChain).
    CrewAI requires its own LLM class, not LangChain's ChatOllama etc.
    """
    provider = os.getenv("LLM_PROVIDER", "ollama").lower()

    if provider == "ollama":
        from crewai import LLM
        model     = os.getenv("OLLAMA_MODEL", "llama3.2")
        base_url  = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        print(f"  🤖 Using Ollama: {model} at {base_url}")
        return LLM(
            model=f"ollama/{model}",
            base_url=base_url,
            temperature=temperature,
        )

    elif provider == "groq":
        from crewai import LLM
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY not set in .env")
        model = os.getenv("GROQ_MODEL", "groq/llama-3.3-70b-versatile")
        print(f"  🤖 Using Groq: {model}")
        return LLM(
            model=model,
            api_key=api_key,
            temperature=temperature,
        )

    elif provider == "gemini":
        from crewai import LLM
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set in .env")
        model = os.getenv("GEMINI_MODEL", "gemini/gemini-2.0-flash")
        print(f"  🤖 Using Gemini: {model}")
        return LLM(
            model=model,
            api_key=api_key,
            temperature=temperature,
        )

    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER: '{provider}'. Choose: ollama | groq | gemini"
        )


# ── Test ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Testing LLM connection...")
    llm = get_llm()
    response = llm.call("Say 'Fair Districts GA AI is working!' and nothing else.")
    print(f"Response: {response}")