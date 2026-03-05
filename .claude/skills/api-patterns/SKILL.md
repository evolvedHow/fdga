---
name: api-patterns
description: FastAPI backend patterns, DuckDB query conventions, async data fetching, error handling, and API integration for the analytics dashboard. Use when writing API routes, database queries, React data fetching hooks, or backend data pipelines.
allowed-tools: Read, Write, Bash, Glob
---

## Backend Stack
- **Framework**: FastAPI with async endpoints
- **Database**: DuckDB (file-based, read-heavy analytics queries)
- **Package manager**: uv (not pip, not poetry)
- **LLM providers**: Ollama (local), Groq, Gemini — always use multi-provider abstraction

## FastAPI Conventions
- All routes return typed Pydantic response models
- Use `async def` for all endpoints that touch DB or external services
- Error responses: always return `{"error": "...", "detail": "..."}` with appropriate HTTP status
- Add CORS middleware for local dev (allow localhost:3000, localhost:5173)
- Health check endpoint at `GET /health` required on all services

## DuckDB Query Patterns
- Use parameterized queries — never f-string SQL
- For analytics aggregations, prefer DuckDB's native window functions over Python post-processing
- Cache expensive queries with a simple TTL dict in memory (avoid Redis dependency for OSS budget)
- Always close connections after use; use context managers

## React Data Fetching
- Use `fetch` with `async/await` — no Axios dependency unless already in project
- All API calls wrapped in custom hooks: `useDistrictData()`, `useMetrics()`, etc.
- Loading/error/data states always handled — never render without null checks
- Retry logic: 2 retries with 500ms backoff for transient failures

## Environment
- API base URL from `VITE_API_URL` env var (never hardcoded)
- Never commit `.env` files; always provide `.env.example`