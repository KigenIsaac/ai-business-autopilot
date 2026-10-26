# AI Business Autopilot

A standalone FastAPI application for AI-assisted business planning, evidence-backed research, prospect qualification, freelance opportunity discovery, outreach drafting, Gmail Drafts integration, and persistent task history.

## Deployed service

The app is served at `https://fx.ketronics.co.ke/autopilot/` through the existing FX Edge Nginx virtual host and its existing Basic Auth gate. The app binds only to loopback at `127.0.0.1:8092`; it does not replace FX Edge.

## Features

- AI business planner with constraints, research context, prioritized actions, risks, and metrics.
- Tavily-backed research with source URLs and an AI evidence summary.
- AI prospect scoring and conversion recommendations.
- Ranked freelance/contract opportunity discovery from web search results.
- Personalized outreach drafts saved to a persistent SQLite database.
- Optional Google OAuth flow to save a reviewed draft into Gmail Drafts; email is never sent by this app.
- OAuth state expiry/replay protection and encrypted token storage using Fernet.
- Suppression list that blocks drafts to opted-out addresses.
- Duplicate-recipient/subject draft protection for a 24-hour window.
- Persistent task history and live metrics.
- Contracts, payments, financial actions, sensitive actions, and external commitments require human review.

## Activate AI, research, and Gmail

The service reads its private environment file at `/etc/ai-business-autopilot.env`. Set one LLM key (`OPENAI_API_KEY`, `OPENROUTER_API_KEY`, or `LLM_API_KEY`) and optionally `LLM_MODEL` / `LLM_BASE_URL`. Set `TAVILY_API_KEY` (or `SEARCH_API_KEY`) to enable live research and job discovery.

To enable Gmail Drafts, configure `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` for a Google OAuth Web application, add the exact redirect URI `https://fx.ketronics.co.ke/autopilot/api/gmail/callback` in Google Cloud Console, and enable the Gmail API. The server has a generated `TOKEN_ENCRYPTION_KEY`; keep it private and backed up. OAuth scope is limited to `gmail.compose`. Connecting Gmail and creating drafts does not send messages.

Provider and Google OAuth credentials are not present in the current server environment, so provider-dependent requests return a clear configuration error until credentials are installed. The dashboard, database, safety controls, and health/status endpoints are running.

## Local run

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8092
```

Health: `/healthz` · Readiness: `/readyz` · Status: `/api/status` · API docs: `/api/docs`.

## Security

Never commit API keys, OAuth client secrets, access tokens, customer data, `.env` files, or production databases. Outbound sending is disabled. Review AI output and evidence before acting.
