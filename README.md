# AI Business Autopilot

A standalone FastAPI application for AI-assisted business operations, research, lead qualification, and review-gated workflows.

## Safety defaults
- Outbound email is draft-only; the application does not send emails.
- Sensitive, contractual, and financial actions require human review.
- Opt-out and duplicate-send protections are part of the intended workflow policy.
- Configure secrets through environment variables; never commit credentials or local databases.

## Project status
This repository is being prepared for deployment at https://fx.ketronics.co.ke/autopilot/ as a separate application. It must not replace or modify FX Edge.

The application source bundle and its tests are maintained separately until the full source transfer is complete. Do not treat this repository as deployed until the VPS health checks and route verification have passed.

## Security note
This is a public repository. Do not put API keys, OAuth client secrets, JWT secrets, access tokens, customer data, or production database files in commits.
