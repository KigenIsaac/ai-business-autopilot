from __future__ import annotations
import base64, hashlib, json, os, secrets, sqlite3, time, urllib.parse, urllib.request, urllib.error
from email.message import EmailMessage
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

APP_NAME = "AI Business Autopilot"
DATA_DIR = Path(os.getenv("AUTOPILOT_DATA_DIR", "/var/lib/ai-business-autopilot"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "autopilot.sqlite3"
app = FastAPI(title=APP_NAME, version="1.0.0", docs_url="/api/docs", redoc_url=None)

def now() -> str:
    return datetime.now(timezone.utc).isoformat()

def db():
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("""CREATE TABLE IF NOT EXISTS tasks(
      id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, title TEXT NOT NULL,
      input_json TEXT NOT NULL, output_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'completed',
      created_at TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS drafts(
      id INTEGER PRIMARY KEY AUTOINCREMENT, recipient TEXT NOT NULL DEFAULT '',
      subject TEXT NOT NULL, body TEXT NOT NULL, source TEXT NOT NULL DEFAULT '',
      approved INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS integrations(name TEXT PRIMARY KEY, token_cipher TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS oauth_states(state_hash TEXT PRIMARY KEY, created_at REAL NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS suppressions(
      email TEXT PRIMARY KEY, reason TEXT NOT NULL DEFAULT 'opted_out', created_at TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS events(
      id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, data_json TEXT NOT NULL, created_at TEXT NOT NULL)""")
    columns = {r[1] for r in c.execute("PRAGMA table_info(drafts)").fetchall()}
    if "gmail_draft_id" not in columns: c.execute("ALTER TABLE drafts ADD COLUMN gmail_draft_id TEXT")
    if "gmail_pushed_at" not in columns: c.execute("ALTER TABLE drafts ADD COLUMN gmail_pushed_at TEXT")
    c.commit()
    return c


def token_cipher():
    from cryptography.fernet import Fernet
    key = os.getenv("TOKEN_ENCRYPTION_KEY", "").strip()
    if not key:
        raise HTTPException(status_code=503, detail="Gmail token encryption is not configured.")
    try: return Fernet(key.encode())
    except Exception: raise HTTPException(status_code=503, detail="TOKEN_ENCRYPTION_KEY is invalid.")

def stored_google_tokens():
    with db() as c:
        row = c.execute("SELECT token_cipher FROM integrations WHERE name='google_gmail'").fetchone()
    if not row: return None
    try: return json.loads(token_cipher().decrypt(row["token_cipher"].encode()).decode())
    except HTTPException: raise
    except Exception: raise HTTPException(status_code=500, detail="Stored Gmail token could not be decrypted; reconnect Gmail.")

def save_google_tokens(tokens):
    encrypted = token_cipher().encrypt(json.dumps(tokens).encode()).decode()
    with db() as c:
        c.execute("INSERT INTO integrations(name,token_cipher,updated_at) VALUES('google_gmail',?,?) ON CONFLICT(name) DO UPDATE SET token_cipher=excluded.token_cipher,updated_at=excluded.updated_at", (encrypted, now()))

def google_access_token():
    tokens = stored_google_tokens()
    if not tokens: raise HTTPException(status_code=409, detail="Gmail is not connected. Connect Gmail first.")
    if float(tokens.get("expires_at",0)) < time.time()+60:
        refresh = tokens.get("refresh_token")
        if not refresh: raise HTTPException(status_code=409, detail="Gmail refresh token is missing; reconnect Gmail.")
        payload=urllib.parse.urlencode({"client_id":os.getenv("GOOGLE_CLIENT_ID",""),"client_secret":os.getenv("GOOGLE_CLIENT_SECRET",""),"refresh_token":refresh,"grant_type":"refresh_token"}).encode()
        req=urllib.request.Request("https://oauth2.googleapis.com/token",data=payload,headers={"Content-Type":"application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req,timeout=30) as r: fresh=json.loads(r.read())
            tokens.update(fresh); tokens["expires_at"]=time.time()+int(fresh.get("expires_in",3600)); save_google_tokens(tokens)
        except Exception: raise HTTPException(status_code=502,detail="Could not refresh Gmail access token.")
    return tokens["access_token"]

def configured():
    return bool(os.getenv("OPENAI_API_KEY") or os.getenv("OPENROUTER_API_KEY") or os.getenv("LLM_API_KEY"))

def llm(prompt: str, system: str = "You are a careful AI business operator. Be practical, evidence-aware, and concise. Never invent facts. Clearly label assumptions.") -> str:
    key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY") or os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise HTTPException(status_code=503, detail="AI provider key is not configured on the server.")
    base = os.getenv("LLM_BASE_URL") or ("https://openrouter.ai/api/v1" if os.getenv("OPENROUTER_API_KEY") else "https://api.openai.com/v1")
    model = os.getenv("LLM_MODEL") or ("openai/gpt-4.1-mini" if os.getenv("OPENROUTER_API_KEY") else "gpt-4.1-mini")
    payload = json.dumps({"model": model, "temperature": 0.25, "messages":[{"role":"system","content":system},{"role":"user","content":prompt}]}).encode()
    req = urllib.request.Request(base.rstrip("/")+"/chat/completions", data=payload, headers={"Authorization":"Bearer "+key,"Content-Type":"application/json","User-Agent":"AI-Business-Autopilot/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=90) as res: data=json.loads(res.read())
        return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:600]
        raise HTTPException(status_code=502, detail=f"AI provider returned HTTP {e.code}: {detail}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI provider request failed: {type(e).__name__}")

def research(query: str, limit: int = 6) -> list[dict[str, str]]:
    key = os.getenv("TAVILY_API_KEY") or os.getenv("SEARCH_API_KEY")
    if not key:
        return []
    payload=json.dumps({"api_key":key,"query":query,"search_depth":"advanced","max_results":max(1,min(limit,10)),"include_answer":True}).encode()
    req=urllib.request.Request("https://api.tavily.com/search",data=payload,headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=30) as r: d=json.loads(r.read())
        out=[]
        if d.get("answer"): out.append({"title":"Search summary","url":"","content":d["answer"]})
        for x in d.get("results",[]): out.append({"title":str(x.get("title",""))[:300],"url":str(x.get("url",""))[:1000],"content":str(x.get("content",""))[:1800]})
        return out
    except Exception as e:
        raise HTTPException(status_code=502,detail=f"Research provider failed: {type(e).__name__}")

def log_task(kind: str, title: str, inp: Any, out: Any):
    with db() as c:
        c.execute("INSERT INTO tasks(kind,title,input_json,output_json,status,created_at) VALUES(?,?,?,?,?,?)",
          (kind,title,json.dumps(inp,ensure_ascii=False),json.dumps(out,ensure_ascii=False),"completed",now()))
        c.execute("INSERT INTO events(kind,data_json,created_at) VALUES(?,?,?)",(kind,json.dumps({"title":title}),now()))

class Goal(BaseModel):
    goal: str = Field(min_length=3,max_length=3000)
    business_context: str = Field(default="",max_length=8000)
    constraints: str = Field(default="",max_length=4000)
class ResearchRequest(BaseModel):
    query: str = Field(min_length=3,max_length=1000)
    limit: int = Field(default=6,ge=1,le=10)
class OutreachRequest(BaseModel):
    prospect: str = Field(min_length=2,max_length=1000)
    offer: str = Field(min_length=2,max_length=2000)
    evidence: str = Field(default="",max_length=5000)
    tone: str = Field(default="helpful and specific",max_length=100)
    recipient_email: str = Field(default="",max_length=320)
class ScoreRequest(BaseModel):
    prospect: str = Field(min_length=2,max_length=2000)
    evidence: str = Field(default="",max_length=5000)
class JobSearchRequest(BaseModel):
    query: str = Field(min_length=3,max_length=1000)
    location: str = Field(default="",max_length=200)
    skills: str = Field(default="",max_length=1000)
    limit: int = Field(default=8,ge=1,le=10)
class SuppressionRequest(BaseModel):
    email: str = Field(min_length=3,max_length=320)
    reason: str = Field(default="opted_out",max_length=100)
class TaskCreate(BaseModel):
    title: str = Field(min_length=2,max_length=300)
    details: str = Field(default="",max_length=3000)
    due_date: str = Field(default="",max_length=40)

@app.get("/healthz")
def healthz(): return {"status":"ok","service":"ai-business-autopilot","version":app.version}
@app.get("/readyz")
def readyz():
    try:
        with db() as c: c.execute("SELECT 1").fetchone()
        return {"status":"ready","database":"ok","ai_configured":configured(),"research_configured":bool(os.getenv("TAVILY_API_KEY") or os.getenv("SEARCH_API_KEY"))}
    except Exception: raise HTTPException(status_code=503,detail="Database unavailable")
@app.get("/api/status")
def status():
    return {"service":APP_NAME,"version":app.version,"ai_configured":configured(),"research_configured":bool(os.getenv("TAVILY_API_KEY") or os.getenv("SEARCH_API_KEY")),"gmail_configured":bool(os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET")),"email_mode":"draft_only","automatic_sending":False,"human_review_required_for":["contracts","payments","financial actions","sensitive actions","external commitments"],"timestamp":now()}
@app.post("/api/plan")
def plan(req: Goal):
    findings=research(req.goal+" "+req.business_context,5)
    prompt=f"""Create an actionable business execution plan. Return clear sections: executive_summary, assumptions, market_and_customer, strategy, prioritized_actions, sales_conversion, risks_and_guardrails, metrics, next_7_days. Use concrete steps, owners/roles, estimated effort, success measures. Do not invent verified facts. Mark unknowns and assumptions. No external action is authorized.
GOAL: {req.goal}
BUSINESS CONTEXT: {req.business_context or 'Not supplied'}
CONSTRAINTS: {req.constraints or 'Not supplied'}
RESEARCH EVIDENCE (treat as unverified until sources reviewed): {json.dumps(findings,ensure_ascii=False)}"""
    answer=llm(prompt)
    result={"plan":answer,"research":findings,"created_at":now(),"requires_human_approval_for_execution":True}
    log_task("plan",req.goal,req.model_dump(),result)
    return result
@app.post("/api/research")
def do_research(req: ResearchRequest):
    findings=research(req.query,req.limit)
    if not findings: raise HTTPException(status_code=503,detail="Research requires TAVILY_API_KEY or SEARCH_API_KEY in server environment.")
    summary=llm("Summarize these search results for this question: "+req.query+"\nDistinguish sourced facts from inference; identify gaps and next checks. Cite URLs inline.\n"+json.dumps(findings,ensure_ascii=False))
    result={"query":req.query,"sources":findings,"analysis":summary,"created_at":now()}
    log_task("research",req.query,req.model_dump(),result)
    return result
@app.post("/api/sales/score")
def score(req: ScoreRequest):
    answer=llm(f"""Score this prospect from 0 to 100 for fit and likelihood to convert. Return: score, rationale, evidence_strength, fit_signals, risks, missing_information, recommended_next_step, suggested_personalization. Do not claim facts absent from evidence.
Prospect: {req.prospect}
Evidence: {req.evidence or 'No evidence supplied'}""")
    result={"assessment":answer,"created_at":now()}
    log_task("sales_score",req.prospect,req.model_dump(),result)
    return result
@app.post("/api/outreach/draft")
def draft(req: OutreachRequest):
    recipient=req.recipient_email.strip().lower()
    if recipient:
        with db() as c:
            blocked=c.execute("SELECT 1 FROM suppressions WHERE email=?",(recipient,)).fetchone()
        if blocked: raise HTTPException(status_code=409,detail="Recipient is on the suppression list; outreach draft blocked.")
    prompt=f"""Write one concise, personalized first-contact sales email with a truthful subject and useful call to action. Only use provided facts; do not fabricate personal details, prior contact, testimonials, results, or urgency. Avoid spammy language. Include a brief reason this offer might fit and one low-friction next step. Return JSON with subject and body only.
Prospect: {req.prospect}
Offer: {req.offer}
Evidence: {req.evidence or 'None provided'}
Tone: {req.tone}"""
    raw=llm(prompt,"You are an ethical B2B sales copywriter. Accuracy and relevance outrank persuasion. Never imply email was sent.")
    subject,body="Draft outreach",""
    try:
        x=json.loads(raw); subject=str(x.get("subject",subject)); body=str(x.get("body",""))
    except Exception: body=raw
    if not body.strip(): raise HTTPException(status_code=502,detail="AI returned an empty draft")
    with db() as c:
        if recipient and c.execute("SELECT 1 FROM drafts WHERE lower(recipient)=? AND lower(subject)=? AND julianday(created_at)>=julianday('now','-1 day') LIMIT 1",(recipient,subject.lower())).fetchone():
            raise HTTPException(status_code=409,detail="Duplicate outreach draft blocked for this recipient and subject within 24 hours.")
        cur=c.execute("INSERT INTO drafts(recipient,subject,body,source,approved,created_at) VALUES(?,?,?,?,0,?)",(recipient,subject,body,req.prospect,now()))
        did=cur.lastrowid
    result={"draft_id":did,"recipient":req.recipient_email,"subject":subject,"body":body,"status":"saved_draft_not_sent","human_review_required":True,"created_at":now()}
    log_task("outreach_draft",req.prospect,req.model_dump(),result)
    return result

@app.post("/api/jobs/search")
def find_jobs(req: JobSearchRequest):
    query = "freelance contract remote jobs " + req.query + " " + req.location + " " + req.skills
    findings = research(query, req.limit)
    if not findings:
        raise HTTPException(status_code=503, detail="Job discovery requires TAVILY_API_KEY or SEARCH_API_KEY in the server environment.")
    analysis = llm("Evaluate these search results for legitimate freelance/contract opportunities. Return a ranked list with role, buyer/employer, source URL, stated requirements, fit rationale, application next step, confidence, and any scam/red-flag signals. Do not invent pay, deadlines, or requirements; label unavailable details unknown. Query: " + query + "\nResults: " + json.dumps(findings, ensure_ascii=False))
    result = {"query": query.strip(), "sources": findings, "ranked_opportunities": analysis, "created_at": now(), "human_review_required_before_applying": True}
    log_task("job_discovery", req.query, req.model_dump(), result)
    return result

@app.post("/api/suppressions")
def suppress(req: SuppressionRequest):
    email = req.email.strip().lower()
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        raise HTTPException(status_code=422, detail="A valid email address is required.")
    with db() as c:
        c.execute("INSERT INTO suppressions(email,reason,created_at) VALUES(?,?,?) ON CONFLICT(email) DO UPDATE SET reason=excluded.reason", (email, req.reason, now()))
    return {"email": email, "suppressed": True, "reason": req.reason}

@app.get("/api/suppressions")
def list_suppressions():
    with db() as c:
        rows = c.execute("SELECT email,reason,created_at FROM suppressions ORDER BY created_at DESC LIMIT 500").fetchall()
    return {"suppressions": [dict(r) for r in rows]}


@app.get("/api/gmail/status")
def gmail_status():
    configured_oauth = bool(os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET") and os.getenv("GOOGLE_REDIRECT_URI") and os.getenv("TOKEN_ENCRYPTION_KEY"))
    with db() as c:
        row=c.execute("SELECT updated_at FROM integrations WHERE name='google_gmail'").fetchone()
    return {"oauth_configured":configured_oauth,"connected":bool(row),"connected_at":row["updated_at"] if row else None,"scope":"gmail.compose","sending_enabled":False}

@app.get("/api/gmail/connect")
def gmail_connect():
    client=os.getenv("GOOGLE_CLIENT_ID","").strip()
    secret=os.getenv("GOOGLE_CLIENT_SECRET","").strip()
    redirect=os.getenv("GOOGLE_REDIRECT_URI","").strip()
    if not client or not secret or not redirect or not os.getenv("TOKEN_ENCRYPTION_KEY","").strip():
        raise HTTPException(status_code=503,detail="Configure GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI, and TOKEN_ENCRYPTION_KEY first.")
    if not redirect.startswith("https://"):
        raise HTTPException(status_code=503,detail="Gmail OAuth redirect URI must use HTTPS.")
    state=secrets.token_urlsafe(32)
    with db() as c:
        c.execute("DELETE FROM oauth_states WHERE created_at<?",(time.time()-600,))
        c.execute("INSERT INTO oauth_states(state_hash,created_at) VALUES(?,?)",(hashlib.sha256(state.encode()).hexdigest(),time.time()))
    params={"client_id":client,"redirect_uri":redirect,"response_type":"code","scope":"https://www.googleapis.com/auth/gmail.compose","access_type":"offline","prompt":"consent","include_granted_scopes":"true","state":state}
    return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?"+urllib.parse.urlencode(params),status_code=302)

@app.get("/api/gmail/callback")
def gmail_callback(code:str="",state:str="",error:str=""):
    if error: raise HTTPException(status_code=400,detail="Google OAuth was cancelled or denied.")
    if not code or not state: raise HTTPException(status_code=400,detail="Missing OAuth code or state.")
    state_hash=hashlib.sha256(state.encode()).hexdigest()
    with db() as c:
        row=c.execute("SELECT created_at FROM oauth_states WHERE state_hash=?",(state_hash,)).fetchone()
        c.execute("DELETE FROM oauth_states WHERE state_hash=?",(state_hash,))
    if not row or time.time()-row["created_at"]>600: raise HTTPException(status_code=400,detail="OAuth state is invalid, expired, or already used.")
    payload=urllib.parse.urlencode({"code":code,"client_id":os.getenv("GOOGLE_CLIENT_ID",""),"client_secret":os.getenv("GOOGLE_CLIENT_SECRET",""),"redirect_uri":os.getenv("GOOGLE_REDIRECT_URI",""),"grant_type":"authorization_code"}).encode()
    req=urllib.request.Request("https://oauth2.googleapis.com/token",data=payload,headers={"Content-Type":"application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req,timeout=30) as r: tokens=json.loads(r.read())
    except Exception: raise HTTPException(status_code=502,detail="Google OAuth token exchange failed.")
    old=stored_google_tokens() or {}
    tokens["refresh_token"]=tokens.get("refresh_token") or old.get("refresh_token")
    if not tokens.get("refresh_token"): raise HTTPException(status_code=502,detail="Google did not return a refresh token. Revoke this app's access in Google Account settings and reconnect.")
    tokens["expires_at"]=time.time()+int(tokens.get("expires_in",3600))
    save_google_tokens(tokens)
    return RedirectResponse("/autopilot/?gmail=connected",status_code=303)

@app.post("/api/drafts/{draft_id}/gmail")
def push_draft_to_gmail(draft_id:int):
    with db() as c:
        row=c.execute("SELECT * FROM drafts WHERE id=?",(draft_id,)).fetchone()
        if not row: raise HTTPException(status_code=404,detail="Draft not found.")
        if row["gmail_draft_id"]: return {"draft_id":draft_id,"gmail_draft_id":row["gmail_draft_id"],"status":"already_in_gmail","sent":False}
        recipient=(row["recipient"] or "").strip().lower()
        if recipient and c.execute("SELECT 1 FROM suppressions WHERE email=?",(recipient,)).fetchone():
            raise HTTPException(status_code=409,detail="Recipient is on the suppression list; Gmail draft creation blocked.")
    token=google_access_token()
    message=EmailMessage()
    if recipient: message["To"]=recipient
    message["Subject"]=row["subject"]
    message.set_content(row["body"])
    raw=base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip("=")
    payload=json.dumps({"message":{"raw":raw}}).encode()
    req=urllib.request.Request("https://gmail.googleapis.com/gmail/v1/users/me/drafts",data=payload,headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=30) as r: created=json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise HTTPException(status_code=502,detail=f"Gmail draft creation failed with HTTP {e.code}.")
    with db() as c:
        c.execute("UPDATE drafts SET gmail_draft_id=?,gmail_pushed_at=? WHERE id=? AND gmail_draft_id IS NULL",(created.get("id",""),now(),draft_id))
    return {"draft_id":draft_id,"gmail_draft_id":created.get("id"),"status":"created_in_gmail_not_sent","sent":False}

@app.get("/api/drafts")
def list_drafts():
    with db() as c: rows=c.execute("SELECT * FROM drafts ORDER BY id DESC LIMIT 100").fetchall()
    return {"drafts":[dict(r) for r in rows]}
@app.get("/api/tasks")
def list_tasks(limit:int=Query(default=50,ge=1,le=100)):
    with db() as c: rows=c.execute("SELECT id,kind,title,status,created_at,output_json FROM tasks ORDER BY id DESC LIMIT ?",(limit,)).fetchall()
    out=[]
    for r in rows:
        x=dict(r)
        try: x["output"]=json.loads(x.pop("output_json"))
        except Exception: x["output"]=x.pop("output_json","")
        out.append(x)
    return {"tasks":out}
@app.post("/api/tasks")
def create_task(req: TaskCreate):
    result={"details":req.details,"due_date":req.due_date,"created_at":now()}
    log_task("manual_task",req.title,req.model_dump(),result)
    return {"title":req.title,**result,"status":"saved"}
@app.get("/api/metrics")
def metrics():
    with db() as c:
        total=c.execute("SELECT COUNT(*) n FROM tasks").fetchone()["n"]
        kinds=c.execute("SELECT kind,COUNT(*) n FROM tasks GROUP BY kind").fetchall()
        drafts=c.execute("SELECT COUNT(*) n FROM drafts").fetchone()["n"]
        recent=c.execute("SELECT created_at,kind,title FROM tasks ORDER BY id DESC LIMIT 8").fetchall()
    return {"tasks_total":total,"drafts_saved":drafts,"by_kind":{r["kind"]:r["n"] for r in kinds},"recent":[dict(r) for r in recent],"source":"live_database"}
@app.get("/",response_class=HTMLResponse)
def dashboard():
    return HTMLResponse(r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AI Business Autopilot</title><style>
:root{color-scheme:dark;--bg:#0b1020;--card:#121a2c;--muted:#9aa9c1;--line:#27334b;--accent:#82e6c5}*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at top,#172747,var(--bg) 60%);font:16px system-ui;color:#edf3ff}main{max-width:1120px;margin:auto;padding:26px 16px}header{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.logo{width:44px;height:44px;border-radius:13px;background:linear-gradient(135deg,#82e6c5,#77a9ff);color:#081321;display:grid;place-items:center;font-weight:900;font-size:21px}h1{font-size:clamp(25px,5vw,36px);margin:0}h2{font-size:17px;margin:0 0 12px}p,.muted{color:var(--muted);line-height:1.5}.pill{border:1px solid #3c6a60;color:var(--accent);border-radius:99px;padding:5px 10px;font-size:12px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin-top:20px}.card,.panel{background:linear-gradient(150deg,#16223a,#10182a);border:1px solid var(--line);border-radius:16px;padding:18px}.big{font-size:23px;font-weight:750;margin:7px 0}.layout{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,390px),1fr));gap:14px;margin-top:15px}.panel{margin-top:0}label{display:block;margin:13px 0 6px;color:#cbd6e8;font-size:14px}textarea,input,select{width:100%;background:#0b1222;color:white;border:1px solid #33415d;border-radius:10px;padding:11px;font:inherit}textarea{resize:vertical}button{background:var(--accent);border:0;border-radius:10px;padding:11px 14px;font-weight:750;color:#071721;cursor:pointer;margin-top:12px}button:disabled{opacity:.5}pre{white-space:pre-wrap;overflow-wrap:anywhere;color:#c9d8ee;font:14px/1.55 ui-monospace,monospace}.result{border-top:1px solid var(--line);margin-top:15px;padding-top:10px}.warn{color:#f5d99a;font-size:13px;margin-top:18px}.nav{display:flex;gap:8px;flex-wrap:wrap;margin-top:15px}.nav button{background:#24344f;color:#e9f2ff}.nav button.active{background:var(--accent);color:#071721}footer{color:var(--muted);font-size:12px;margin:22px 0}</style></head><body><main>
<header><div class="logo">A</div><div><h1>AI Business Autopilot</h1><div class="muted">Business intelligence · sales conversion · research · execution queue</div></div><span class="pill" id="mode">CONNECTING</span></header>
<div class="grid"><section class="card"><h2>AI engine</h2><div class="big" id="ai">Checking…</div><div class="muted">Provider connection</div></section><section class="card"><h2>Research</h2><div class="big" id="research">Checking…</div><div class="muted">Evidence gathering</div></section><section class="card"><h2>Saved tasks</h2><div class="big" id="tasks">—</div><div class="muted">Persisted in database</div></section><section class="card"><h2>Email safety</h2><div class="big">Draft only</div><div class="muted">No email is sent automatically</div></section></div>
<div class="nav"><button class="active" data-tab="plan">Business planner</button><button data-tab="research">Research</button><button data-tab="sales">Sales conversion</button><button data-tab="jobs">Find freelance work</button><button data-tab="draft">Outreach draft</button><button data-tab="drafts">Saved drafts</button><button data-tab="gmail">Gmail connection</button><button data-tab="history">History & metrics</button></div>
<div class="layout"><section class="panel" id="work"></section><section class="panel"><h2>AI output / activity</h2><div class="muted">Results are saved automatically after successful AI runs.</div><div id="output" class="result"><pre>Choose a workspace and submit a request.</pre></div></section></div>
<div class="warn">Safety guardrails: outbound sending is disabled. Review AI output and sources before acting. Contracts, payments, financial actions, sensitive actions and external commitments require human approval.</div><footer>AI Business Autopilot · Separate service · FX Edge is not modified</footer></main><script>
const $=s=>document.querySelector(s);let tab='plan';function formFor(t){const forms={
plan:['Business goal','goal','textarea','e.g. Win 5 new clients in the next 30 days','Business context','context','textarea','Your offer, customers, location, price, strengths…','Constraints','constraints','textarea','Budget, time, must-not-do…'],
research:['Research question','query','input','Find target customers, competitors, current market signals…'],
sales:['Prospect or target customer','prospect','textarea','Company, industry, needs and any known signals…','Evidence / notes','evidence','textarea','Paste only facts you can substantiate…'],jobs:['Job type / search terms','query','input','Freelance AI, web development, writing, data…','Location / remote preference','location','input','Remote, Kenya, worldwide…','Skills / experience','skills','textarea','Skills, portfolio, experience and preferences…'],
draft:['Prospect','prospect','textarea','Company, role, needs and relevant context…','Your offer','offer','textarea','What value do you provide?','Evidence / personalization','evidence','textarea','Only grounded facts; leave blank if unknown…','Recipient email (optional)','recipient_email','input','name@example.com']
};const a=forms[t];let html='<h2>'+({plan:'AI business planner',research:'Evidence-backed research',sales:'Lead qualification & conversion',jobs:'Freelance opportunity discovery',draft:'Personalized outreach draft'}[t])+'</h2>';for(let i=0;i<a.length;i+=4){html+='<label>'+a[i]+'</label><'+a[i+2]+' id="'+a[i+1]+'" placeholder="'+a[i+3]+'" '+(a[i+2]==='textarea'?'rows="3"':'')+'></'+a[i+2]+'>'}if(t==='research')html+='<label>Number of sources (1–10)</label><input id="limit" type="number" min="1" max="10" value="6">';html+='<button id="submit">Run AI '+({plan:'plan',research:'research',sales:'assessment',draft:'draft'}[t])+'</button>';return html}
function switchTab(t){tab=t;document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===t));$('#work').innerHTML=t==='history'?'<h2>Activity history</h2><button id="refresh">Refresh activity</button><div id="history"></div>':t==='drafts'?'<h2>Saved outreach drafts</h2><p>Push reviewed drafts into Gmail Drafts; nothing is sent.</p><button id="refreshdrafts">Refresh drafts</button><div id="draftlist"></div>':t==='gmail'?'<h2>Gmail draft integration</h2><p>Connect Gmail to save reviewed drafts into your Gmail Drafts folder. This app never sends email.</p><button id="gmailconnect">Connect Gmail</button><div id="gmailstatus"></div>':formFor(t);if(t==='history')loadHistory();else if(t==='drafts')loadDrafts();else if(t==='gmail')loadGmail();else $('#submit').onclick=submit}
const API=location.pathname.startsWith('/autopilot')?'/autopilot/api':'/api';async function api(path,body){const target=path.startsWith('/api/')?API+path.slice(4):path;const r=await fetch(target,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});const d=await r.json();if(!r.ok)throw Error(d.detail||('HTTP '+r.status));return d}
async function submit(){const b=$('#submit');b.disabled=true;$('#output').innerHTML='<pre>Running…</pre>';try{let p={};$('#work').querySelectorAll('input,textarea').forEach(x=>p[x.id]=x.value);let path='/api/plan';if(tab==='research'){path='/api/research';p.limit=Number(p.limit||6)}if(tab==='sales')path='/api/sales/score';if(tab==='jobs'){path='/api/jobs/search';p.limit=8}if(tab==='draft')path='/api/outreach/draft';const d=await api(path,p);$('#output').innerHTML='<pre>'+esc(JSON.stringify(d,null,2))+'</pre>';refreshStatus()}catch(e){$('#output').innerHTML='<pre>Request failed: '+esc(e.message)+'</pre>'}finally{b.disabled=false}}
function esc(s){return s.replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
async function refreshStatus(){try{const s=await api('/api/status');$('#ai').textContent=s.ai_configured?'Configured':'Needs API key';$('#research').textContent=s.research_configured?'Configured':'Needs search key';$('#mode').textContent=s.ai_configured?'AI READY':'SETUP REQUIRED';const m=await api('/api/metrics');$('#tasks').textContent=m.tasks_total}catch(e){$('#mode').textContent='OFFLINE'}}
async function loadDrafts(){const el=$('#draftlist');try{const d=await api('/api/drafts');if(!d.drafts.length){el.innerHTML='<p>No saved drafts yet.</p>';return}el.innerHTML=d.drafts.map(x=>'<article style="border-top:1px solid var(--line);padding:12px 0"><strong>'+esc(x.subject)+'</strong><p>'+esc(x.recipient||'No recipient set')+' · '+esc(x.created_at)+'</p><p>'+esc(x.body.slice(0,360))+'</p><p>'+esc(x.gmail_draft_id?'Already in Gmail Drafts':'Not in Gmail yet')+'</p><button data-push-id="'+x.id+'" '+(x.gmail_draft_id?'disabled':'')+'>Save to Gmail Drafts</button><span id="push-status-'+x.id+'"></span></article>').join('');document.querySelectorAll('[data-push-id]').forEach(b=>b.onclick=async()=>{b.disabled=true;const status=$('#push-status-'+b.dataset.pushId);try{const out=await api('/api/drafts/'+b.dataset.pushId+'/gmail',{});status.textContent=' '+out.status;loadDrafts()}catch(e){status.textContent=' '+e.message;b.disabled=false}})}catch(e){el.textContent=e.message}$('#refreshdrafts').onclick=loadDrafts}
async function loadGmail(){try{const s=await api('/api/gmail/status');$('#gmailstatus').innerHTML='<p>OAuth configured: '+s.oauth_configured+' · Connected: '+s.connected+'</p>';$('#gmailconnect').disabled=!s.oauth_configured;$('#gmailconnect').onclick=()=>location.href=(location.pathname.startsWith('/autopilot')?'/autopilot':'')+'/api/gmail/connect'}catch(e){$('#gmailstatus').textContent=e.message}}
async function loadHistory(){try{const [m,t,d]=await Promise.all([api('/api/metrics'),api('/api/tasks'),api('/api/drafts')]);$('#history').innerHTML='<p>Tasks: '+m.tasks_total+' · Saved drafts: '+m.drafts_saved+'</p><h3>Recent tasks</h3><pre>'+esc(JSON.stringify(t.tasks.slice(0,10),null,2))+'</pre><h3>Recent drafts</h3><pre>'+esc(JSON.stringify(d.drafts.slice(0,10),null,2))+'</pre>'}catch(e){$('#history').textContent=e.message}$('#refresh').onclick=loadHistory}
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>switchTab(b.dataset.tab));switchTab('plan');refreshStatus();
</script></body></html>""")

[executed on device: vmi3624969 (322ac4dd-6dcf-4035-938b-fadde3e82dd6)]