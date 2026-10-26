# AI Business Autopilot

A standalone FastAPI application for AI-assisted business planning, evidence-backed research, prospect qualification, freelance opportunity discovery, outreach drafting, and persistent task history.

## Deployed service

The app is served at `https://fx.ketronics.co.ke/autopilot/` through the existing FX Edge Nginx virtual host and its existing Basic Auth gate. The app binds only to loopback at `127.0.0.1:8092`; it does not replace FX Edge.

## Features

- AI business planner with constraints, research context, prioritized actions, risks, and metrics.
- Tavily-backed research with source URLs and an AI evidence summary.
- AI prospect scoring and conversion recommendations.
- Ranked freelance/contract opportunity discovery from web search results.
- Personalized outreach email drafts saved to a persistent SQLite database.
- Suppression list that blocks drafting to opted-out addresses.
- Duplicate-recipient/subject draft protection for a 24-hour window.
- Persistent task history and live metrics.
- Safety defaults: no email sending; contracts, payments, financial actions, sensitive actions, and external commitments require human review.

## Activate AI and search

The service reads its private environment file at `/etc/ai-business-autopilot.env`. Set one supported LLM key (`OPENAI_API_KEY`, `OPENROUTER_API_KEY`, or `LLM_API_KEY`) and optionally set `LLM_MODEL` / `LLM_BASE_URL`. Set `TAVILY_API_KEY` (or `SEARCH_API_KEY`) to enable live research and job discovery. Never put secrets in this public repository.

AI and search provider credentials are not present in the current server environment, so provider-dependent requests return a clear configuration error until credentials are installed. The dashboard, database, safety controls, and health/status endpoints are running.

## Local run

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8092
```

Health: `/healthz` · Readiness: `/readyz` · Status: `/api/status` · API docs: `/api/docs`.

## Security

Never commit API keys, OAuth client secrets, access tokens, customer data, `.env` files, or production databases. Email sending is deliberately disabled; Gmail OAuth and live sending are not configured in this deployment.
