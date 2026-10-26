# AI Business Autopilot

Standalone FastAPI staging service for a future AI-assisted business operations workspace.

## Current deployment status
The staging dashboard is deployed as an isolated service at `https://fx.ketronics.co.ke/autopilot/`. It runs on loopback port 8092 and is routed through the existing FX Edge Nginx virtual host. The existing FX Edge application and API upstreams are not replaced.

**This is a staging shell, not the complete Stage 9 application.** The full AI planner, database-backed jobs, OAuth/Gmail draft integration, research adapters, and full test suite have not yet been transferred into this repository or activated on the VPS. The planner endpoint intentionally returns a disabled response rather than pretending to perform AI work.

## Safety defaults
- Outbound email is draft-only; this staging service does not send emails.
- Sensitive, contractual, and financial actions require human review.
- No external actions are executed by the staging dashboard.
- No AI provider key is currently configured.
- The existing FX Edge Basic Auth gate also protects this subpath.

## Run locally
```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8092
```

Health endpoint: `/healthz`; readiness endpoint: `/readyz`; status endpoint: `/api/status`.

## Public-repository security
Never commit API keys, OAuth client secrets, JWT secrets, access tokens, customer data, `.env` files, or production databases.
