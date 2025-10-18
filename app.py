# === Netzer Backend (FastAPI) ===
# Handles:
# - Stitch ZAR deposits
# - Withdrawals (pending/complete)
# - VALR ZAR deposit history (read-only)
# -------------------------------------------------------------

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os, httpx, hmac, hashlib, time
from datetime import datetime

app = FastAPI(title="Netzer Backend", version="1.3")

# --- Environment (set these in Render "Environment" tab) ---
SUPABASE_URL = os.getenv("SUPABASE_URL")      # e.g. https://xxxx.supabase.co
SUPABASE_KEY = os.getenv("SUPABASE_KEY")      # Supabase service_role key
VALR_API_KEY = os.getenv("VALR_API_KEY")      # VALR read-only key
VALR_API_SECRET = os.getenv("VALR_API_SECRET")  # VALR secret

# --- CORS (so your Replit dashboard or Vercel frontend can call the API) ---
ALLOWED_ORIGINS = [
    "http://localhost:5173",                  # local dev (Vite)
    "https://netzer-backend.onrender.com",   # your backend on Render
    "https://netzer-dashboard.replit.app",   # optional: your Replit frontend URL
    "*",                                     # safe for now during dev
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

# ---------- VALR signing helper ----------
def sign_valr_request(method: str, path: str, body: str = ""):
    """Create HMAC-SHA512 signature for VALR API requests"""
    timestamp = str(int(time.time() * 1000))
    payload = timestamp + method + path + body
    signature = hmac.new(
        VALR_API_SECRET.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha512
    ).hexdigest()
    return timestamp, signature

# ---------- Stitch deposit webhook ----------
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

# ---------- List deposits ----------
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

# ---------- Withdrawals webhook ----------
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

# ---------- List withdrawals ----------
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

# ---------- VALR deposits ----------
@app.get("/valr/deposits")
async def get_valr_deposits():
    """
    Fetch ZAR deposit history from VALR account (read-only).
    This uses HMAC-SHA512 signing and the /v1/account/deposit-history endpoint.
    """
    if not VALR_API_KEY or not VALR_API_SECRET:
        return {"ok": False, "error": "VALR API keys not set in environment"}

    try:
        path = "/v1/account/deposit-history"
        timestamp, signature = sign_valr_request("GET", path)
        headers = {
            "X-VALR-API-KEY": VALR_API_KEY,
            "X-VALR-SIGNATURE": signature,
            "X-VALR-TIMESTAMP": timestamp,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"https://api.valr.com{path}", headers=headers, timeout=30)

        if resp.status_code < 300:
            return {"ok": True, "valr_deposits": resp.json()}

        return {"ok": False, "error": resp.text}

    except Exception as e:
        return {"ok": False, "error": str(e)}

# ---------- Health Check ----------
@app.get("/")
def health_check():
    return {"status": "Netzer backend live (Supabase + VALR enabled)"}
