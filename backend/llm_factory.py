"""
LLM Factory — Model & Profile Management
==========================================
Two ways to get an LLM for your agents:

  1. get_llm()         — Original API, unchanged. Safe default for existing crews.
                         Uses LLM_PROVIDER + OLLAMA_MODEL from .env.

  2. get_profile(name) — New profile-based API. Loads named profile from
                         config/model_profiles.yaml. Resolves the right model
                         for your current provider automatically.

Profile example:
  from backend.llm_factory import get_profile
  llm = get_profile("precise_analyst")   # deterministic, low temp
  llm = get_profile("creative_writer")   # synthesis, higher temp
  llm = get_profile("strict_critic")     # conservative fact-checker

Provider resolution:
  LLM_PROVIDER=ollama  → ollama_model  (fallback: ollama_fallback)
  LLM_PROVIDER=groq    → cloud_model
  LLM_PROVIDER=gemini  → gemini_model
"""

import os
import yaml
from pathlib import Path
from functools import lru_cache
from dotenv import load_dotenv

load_dotenv()


# ── Profile loader ─────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _load_profiles() -> dict:
    """
    Load model_profiles.yaml once and cache it.
    Searches project root and config/ directory.
    """
    search_paths = [
        Path("config/model_profiles.yaml"),
        Path("model_profiles.yaml"),
        Path(__file__).parent.parent / "config" / "model_profiles.yaml",
        Path(__file__).parent.parent / "model_profiles.yaml",
    ]
    for path in search_paths:
        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f)
            profiles = data.get("profiles", {})
            print(f"  📋 Loaded {len(profiles)} model profiles from {path}")
            return profiles

    print("  ⚠️  model_profiles.yaml not found — using built-in defaults")
    return {}


def _get_default_profiles() -> dict:
    """Built-in fallback if YAML file is missing."""
    return {
        "precise_analyst": {
            "ollama_model": "llama3:8b", "ollama_fallback": "llama3.2:3b",
            "cloud_model": "groq/llama-3.3-70b-versatile",
            "gemini_model": "gemini/gemini-2.0-flash",
            "temperature": 0.05, "top_k": 10, "top_p": 0.80,
            "repeat_penalty": 1.15, "num_ctx": 4096,
        },
        "deep_reasoner": {
            "ollama_model": "deepseek-r1:8b", "ollama_fallback": "llama3:8b",
            "cloud_model": "groq/llama-3.3-70b-versatile",
            "gemini_model": "gemini/gemini-2.0-flash",
            "temperature": 0.15, "top_k": 30, "top_p": 0.88,
            "repeat_penalty": 1.10, "num_ctx": 8192,
        },
        "creative_writer": {
            "ollama_model": "deepseek-r1:8b", "ollama_fallback": "llama3:8b",
            "cloud_model": "groq/llama-3.3-70b-versatile",
            "gemini_model": "gemini/gemini-2.0-flash",
            "temperature": 0.40, "top_k": 50, "top_p": 0.92,
            "repeat_penalty": 1.05, "num_ctx": 8192,
        },
        "strict_critic": {
            "ollama_model": "deepseek-r1:8b", "ollama_fallback": "llama3:8b",
            "cloud_model": "groq/llama-3.3-70b-versatile",
            "gemini_model": "gemini/gemini-2.0-flash",
            "temperature": 0.05, "top_k": 10, "top_p": 0.75,
            "repeat_penalty": 1.20, "num_ctx": 8192,
        },
        "fast_lookup": {
            "ollama_model": "llama3.2:3b", "ollama_fallback": "llama3:8b",
            "cloud_model": "groq/llama-3.1-8b-instant",
            "gemini_model": "gemini/gemini-2.0-flash",
            "temperature": 0.10, "top_k": 20, "top_p": 0.85,
            "repeat_penalty": 1.10, "num_ctx": 2048,
        },
        "balanced_general": {
            "ollama_model": "llama3:8b", "ollama_fallback": "llama3.2:3b",
            "cloud_model": "groq/llama-3.3-70b-versatile",
            "gemini_model": "gemini/gemini-2.0-flash",
            "temperature": 0.10, "top_k": 40, "top_p": 0.90,
            "repeat_penalty": 1.05, "num_ctx": 4096,
        },
    }


# ── Model availability check ───────────────────────────────────────────────────

def _resolve_ollama_model(primary: str, fallback: str, base_url: str) -> str:
    """
    Verify primary model is pulled locally.
    Returns primary if found, fallback otherwise.
    Fails silently if Ollama is unreachable.
    """
    try:
        import httpx
        response = httpx.get(f"{base_url}/api/tags", timeout=3.0)
        if response.status_code == 200:
            available = [m["name"] for m in response.json().get("models", [])]
            primary_base = primary.split(":")[0]
            for m in available:
                if m == primary or m.startswith(primary_base):
                    return primary
            # Primary not found — try fallback
            fallback_base = fallback.split(":")[0]
            for m in available:
                if m == fallback or m.startswith(fallback_base):
                    print(f"  ⚠️  {primary} not pulled locally, "
                          f"falling back to: {fallback}")
                    return fallback
    except Exception:
        pass  # Ollama unreachable — proceed optimistically
    return primary


# ── Profile-based factory ──────────────────────────────────────────────────────

def get_profile(profile_name: str):
    """
    Return a CrewAI LLM configured from a named model profile.

    Args:
        profile_name: Name defined in config/model_profiles.yaml
                      e.g. "precise_analyst", "creative_writer", "strict_critic"

    Returns:
        CrewAI LLM object ready to assign to an Agent

    Usage:
        demographer   = Agent(..., llm=get_profile("precise_analyst"))
        policy_writer = Agent(..., llm=get_profile("creative_writer"))
        critic        = Agent(..., llm=get_profile("strict_critic"))
    """
    profiles = _load_profiles() or _get_default_profiles()

    if profile_name not in profiles:
        available = list(profiles.keys())
        print(f"  ⚠️  Profile '{profile_name}' not found. "
              f"Available: {available}. Falling back to 'balanced_general'.")
        profile_name = "balanced_general"
        if profile_name not in profiles:
            profiles = _get_default_profiles()

    profile  = profiles[profile_name]
    provider = os.getenv("LLM_PROVIDER", "ollama").lower()
    temp     = profile.get("temperature", 0.1)

    # Sampling params supported by Ollama (ignored by cloud providers)
    sampling = {
        k: profile[k]
        for k in ("top_k", "top_p", "repeat_penalty", "num_ctx")
        if k in profile
    }

    if provider == "ollama":
        from crewai import LLM
        base_url = os.getenv("OLLAMA_BASE_URL",
                   os.getenv("OLLAMA_HOST", "http://localhost:11434"))
        primary  = profile.get("ollama_model", "llama3:8b")
        fallback = profile.get("ollama_fallback", "llama3:8b")
        model    = _resolve_ollama_model(primary, fallback, base_url)

        print(f"  🤖 [{profile_name}] ollama/{model} "
              f"temp={temp} top_k={sampling.get('top_k','—')} "
              f"ctx={sampling.get('num_ctx','—')}")

        return LLM(
            model=f"ollama/{model}",
            base_url=base_url,
            temperature=temp,
            **sampling,
        )

    elif provider == "groq":
        from crewai import LLM
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY not set in .env")
        model = profile.get("cloud_model", "groq/llama-3.3-70b-versatile")
        print(f"  🤖 [{profile_name}] {model} temp={temp}")
        return LLM(model=model, api_key=api_key, temperature=temp)

    elif provider == "gemini":
        from crewai import LLM
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set in .env")
        model = profile.get("gemini_model", "gemini/gemini-2.0-flash")
        print(f"  🤖 [{profile_name}] {model} temp={temp}")
        return LLM(model=model, api_key=api_key, temperature=temp)

    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER: '{provider}'. Choose: ollama | groq | gemini"
        )


# ── Original API — unchanged for backward compatibility ────────────────────────

def get_llm(temperature: float = 0.1):
    """
    Original factory function. Kept unchanged — existing crews keep working.
    For new agents, prefer get_profile() instead.
    """
    provider = os.getenv("LLM_PROVIDER", "ollama").lower()

    if provider == "ollama":
        from crewai import LLM
        model    = os.getenv("OLLAMA_MODEL", "llama3.2")
        base_url = os.getenv("OLLAMA_BASE_URL",
                   os.getenv("OLLAMA_HOST", "http://localhost:11434"))
        print(f"  🤖 Using Ollama: {model} at {base_url}")
        return LLM(model=f"ollama/{model}", base_url=base_url, temperature=temperature)

    elif provider == "groq":
        from crewai import LLM
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY not set in .env")
        model = os.getenv("GROQ_MODEL", "groq/llama-3.3-70b-versatile")
        print(f"  🤖 Using Groq: {model}")
        return LLM(model=model, api_key=api_key, temperature=temperature)

    elif provider == "gemini":
        from crewai import LLM
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set in .env")
        model = os.getenv("GEMINI_MODEL", "gemini/gemini-2.0-flash")
        print(f"  🤖 Using Gemini: {model}")
        return LLM(model=model, api_key=api_key, temperature=temperature)

    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER: '{provider}'. Choose: ollama | groq | gemini"
        )


# ── Profile inspector CLI ──────────────────────────────────────────────────────

def list_profiles() -> None:
    """Print all available profiles with their resolved model for current provider."""
    profiles = _load_profiles() or _get_default_profiles()
    provider = os.getenv("LLM_PROVIDER", "ollama").lower()
    model_key = {"ollama": "ollama_model", "groq": "cloud_model",
                 "gemini": "gemini_model"}.get(provider, "ollama_model")

    print(f"\n{'='*62}")
    print(f"  Model Profiles  —  provider: {provider}")
    print(f"{'='*62}")
    for name, p in profiles.items():
        model  = p.get(model_key, "?")
        temp   = p.get("temperature", "?")
        top_k  = p.get("top_k", "?")
        ctx    = p.get("num_ctx", "?")
        agents = ", ".join(p.get("best_for", []))
        desc   = p.get("description", "")
        print(f"\n  {name}")
        print(f"    Model      : {model}")
        print(f"    Temp/Top-K : {temp} / {top_k}  (ctx: {ctx})")
        print(f"    Best for   : {agents}")
        print(f"    Note       : {desc}")
    print(f"\n{'='*62}\n")


# ── CLI entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if "--profiles" in sys.argv or "profiles" in sys.argv:
        list_profiles()
    else:
        print("Testing default LLM connection...")
        llm = get_llm()
        response = llm.call("Say 'LLM factory working!' and nothing else.")
        print(f"Response: {response}")
        print()
        list_profiles()