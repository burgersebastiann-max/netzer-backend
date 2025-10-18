from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os, httpx
from datetime import datetime

app = FastAPI(title="Netzer Backend", version="1.2")

# --- Environment (must be set in Render "Environment" tab) ---
SUPABASE_URL = os.getenv("SUPABASE_URL")            # e.g. https://xxxx.supabase.co
SUPABASE_KEY = os.getenv("SUPABASE_KEY")            # service_role key

# --- CORS so your VS Code dashboard can call the API ---
ALLOWED_ORIGINS = [
    "http://localhost:5173",                        # Vite dev server
    "https://netzer-backend.onrender.com",         # (optional) self
    # add your final dashboard domain later, e.g.:
    # "https://netzer-dashboard.vercel.app",
    "*",                                           # keep for now while developing
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Models ----------
class Deposit(BaseModel):
    client_id: str
    amount_zar: float
    stitch_txid: str

class Withdrawal(BaseModel):
    client_id: str
    amount_zar: float
    withdraw_txid: str

# ---------- Endpoints ----------
@app.post("/webhooks/stitch")
async def handle_stitch_webhook(deposit: Deposit):
    record = {
        "client_id": deposit.client_id,
        "amount_zar": deposit.amount_zar,
        "stitch_txid": deposit.stitch_txid,
        "timestamp": datetime.utcnow().isoformat(),
        "status": "completed",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{SUPABASE_URL}/rest/v1/deposits",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            },
            json=record,
            timeout=20,
        )
    if resp.status_code < 300:
        return {"ok": True, "data": resp.json()}
    return {"ok": False, "error": resp.text}

@app.get("/deposits")
async def list_deposits():
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{SUPABASE_URL}/rest/v1/deposits?select=*",
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
            timeout=20,
        )
    if resp.status_code < 300:
        return {"ok": True, "deposits": resp.json()}
    return {"ok": False, "error": resp.text}

@app.post("/webhooks/withdraw")
async def handle_withdraw_request(withdraw: Withdrawal):
    record = {
        "client_id": withdraw.client_id,
        "amount_zar": withdraw.amount_zar,
        "withdraw_txid": withdraw.withdraw_txid,
        "timestamp": datetime.utcnow().isoformat(),
        "status": "pending",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{SUPABASE_URL}/rest/v1/withdrawals",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            },
            json=record,
            timeout=20,
        )
    if resp.status_code < 300:
        return {"ok": True, "data": resp.json()}
    return {"ok": False, "error": resp.text}

@app.get("/withdrawals")
async def list_withdrawals():
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{SUPABASE_URL}/rest/v1/withdrawals?select=*",
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
            timeout=20,
        )
    if resp.status_code < 300:
        return {"ok": True, "withdrawals": resp.json()}
    return {"ok": False, "error": resp.text}

@app.get("/")
def health_check():
    return {"status": "Netzer backend live (HTTP Supabase mode)"}
