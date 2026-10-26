from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

app = FastAPI(title="AI Business Autopilot", version="0.1.0", docs_url=None, redoc_url=None)

class TaskRequest(BaseModel):
    goal: str = Field(min_length=3, max_length=2000)
    business_context: str = Field(default="", max_length=5000)

@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "ai-business-autopilot"}

@app.get("/readyz")
def readyz():
    return {"status": "ready", "ai_configured": bool(os.getenv("OPENAI_API_KEY") or os.getenv("OPENROUTER_API_KEY"))}

@app.get("/api/status")
def status():
    return {
        "service": "AI Business Autopilot",
        "version": app.version,
        "ai_configured": bool(os.getenv("OPENAI_API_KEY") or os.getenv("OPENROUTER_API_KEY")),
        "email_mode": "draft_only",
        "human_review_required": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

@app.post("/api/plan")
def plan(req: TaskRequest):
    if not (os.getenv("OPENAI_API_KEY") or os.getenv("OPENROUTER_API_KEY")):
        raise HTTPException(status_code=503, detail="AI provider is not configured.")
    raise HTTPException(status_code=501, detail="AI planner is not activated in this staging build.")

@app.get("/", response_class=HTMLResponse)
def dashboard():
    return HTMLResponse("""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Business Autopilot</title><style>
:root{color-scheme:dark;--bg:#0b1020;--card:#121a2c;--muted:#9aa9c1;--line:#27334b;--accent:#82e6c5}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at top,#172747,var(--bg) 60%);font:16px system-ui;color:#edf3ff}
main{max-width:1000px;margin:auto;padding:28px 18px}header{display:flex;align-items:center;gap:14px;margin-bottom:28px}
.logo{width:46px;height:46px;border-radius:14px;background:linear-gradient(135deg,#82e6c5,#77a9ff);color:#081321;display:grid;place-items:center;font-weight:900;font-size:20px}
h1{font-size:clamp(25px,5vw,38px);margin:0}p{color:var(--muted);line-height:1.55}.pill{border:1px solid #3c6a60;color:var(--accent);border-radius:99px;padding:5px 10px;font-size:12px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}.card{background:linear-gradient(150deg,#16223a,#10182a);border:1px solid var(--line);border-radius:18px;padding:20px}
h2{font-size:17px;margin:0 0 10px}.big{font-size:25px;font-weight:750;margin:6px 0}.muted{color:var(--muted);font-size:14px}
.panel{margin-top:16px;background:var(--card);border:1px solid var(--line);border-radius:18px;padding:22px}
label{display:block;margin:14px 0 7px;color:#cbd6e8;font-size:14px}textarea{width:100%;background:#0b1222;color:white;border:1px solid #33415d;border-radius:12px;padding:12px;font:inherit;resize:vertical}
button{margin-top:14px;background:var(--accent);border:0;border-radius:12px;padding:12px 16px;font-weight:750;color:#071721;cursor:pointer}
.notice{background:#2a2417;border:1px solid #66552a;color:#f5d99a;padding:12px 14px;border-radius:12px;font-size:14px;margin-top:16px}
#result{white-space:pre-wrap;color:#c9d8ee;font-size:14px;margin-top:12px}footer{margin:22px 0;color:var(--muted);font-size:12px}
</style></head><body><main>
<header><div class="logo">A</div><div><h1>AI Business Autopilot</h1><p style="margin:4px 0">Your operational intelligence workspace</p></div><span class="pill">STAGING BUILD</span></header>
<div class="grid">
<section class="card"><h2>AI engine</h2><div class="big" id="ai">Checking…</div><div class="muted">Provider configuration status</div></section>
<section class="card"><h2>Outbound email</h2><div class="big">Draft only</div><div class="muted">No emails are sent automatically</div></section>
<section class="card"><h2>Approval policy</h2><div class="big">Human review</div><div class="muted">Sensitive actions require approval</div></section></div>
<div class="notice">Safety mode: this deployment does not execute external actions. The AI planner is disabled until the full implementation and provider configuration are verified.</div>
<section class="panel"><h2>Business planning workspace</h2><p>Describe a business goal to prepare it for AI-assisted planning. This staging interface does not yet run the planner.</p>
<label for="goal">What do you want to achieve?</label><textarea id="goal" rows="3" placeholder="e.g. Improve lead conversion for my service business"></textarea>
<label for="context">Business context (optional)</label><textarea id="context" rows="3" placeholder="Audience, offer, budget, constraints…"></textarea>
<button id="run">Prepare plan request</button><div id="result" role="status"></div></section>
<footer>AI Business Autopilot · Separate service · Does not replace FX Edge</footer></main>
<script>
fetch('api/status').then(r=>r.json()).then(d=>document.querySelector('#ai').textContent=d.ai_configured?'Configured':'Not configured').catch(()=>document.querySelector('#ai').textContent='Unavailable');
document.querySelector('#run').addEventListener('click',()=>{const goal=document.querySelector('#goal').value.trim();const ctx=document.querySelector('#context').value.trim();document.querySelector('#result').textContent=goal.length<3?'Enter a goal of at least 3 characters.':'Request captured in this browser only. Planner is not activated in this staging build.'+(ctx?' Context included.':'')});
</script></body></html>""")
