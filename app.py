# === Netzer Backend (FastAPI) ===
# Version 1.5 — Production-Ready Integration
# ------------------------------------------------------------
# Handles:
# - Stitch deposits via webhook (same JSON test format you use)
# - Withdrawals
# - VALR ZAR deposits (read-only)
# - Auto-matching Stitch → VALR deposits
# - Stores everything in Supabase

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os, httpx, hmac, hashlib, time
from datetime import datetime

app = FastAPI(title="Netzer Backend", version="1.5")

# --- Environment Variables (Render -> Environment tab) ---
SUPABASE_URL = os.getenv("SUPABASE_URL")            # e.g. https://xxxx.supabase.co
SUPABASE_KEY = os.getenv("SUPABASE_KEY")            # Supabase service_role key
VALR_API_KEY = os.getenv("VALR_API_KEY")            # VALR Read-only API key
VALR_API_SECRET = os.getenv("VALR_API_SECRET")      # VALR API secret

# --- CORS setup ---
ALLOWED_ORIGINS = [
    "http://localhost:5173",                        # local dev
    "https://netzer-backend.onrender.com",         # backend (Render)
    "https://netzer-dashboard.replit.app",         # frontend (Replit)
    "*",                                           # open for now
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

# ---------- Helpers ----------
def sign_valr_request(method: str, path: str, body: str = ""):
    """Generate HMAC-SHA512 signature for VALR API requests."""
    timestamp = str(int(time.time() * 1000))
    payload = timestamp + method + path + body
    signature = hmac.new(
        VALR_API_SECRET.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha512
    ).hexdigest()
    return timestamp, signature

def sb_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }

# ---------- Webhook: Stitch deposit ----------
@app.post("/webhooks/stitch")
async def handle_stitch_webhook(deposit: Deposit):
    """Receive deposit from Stitch and store in Supabase (triggered by Stitch webhook)."""
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
            headers={**sb_headers(), "Prefer": "return=representation"},
            json=record,
            timeout=20,
        )
    return {"ok": resp.status_code < 300, "data": resp.json() if resp.status_code < 300 else resp.text}

# ---------- List Deposits ----------
@app.get("/deposits")
async def list_deposits():
    """Return all Stitch deposits from Supabase."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{SUPABASE_URL}/rest/v1/deposits?select=*",
            headers=sb_headers(),
            timeout=20,
        )
    return {"ok": resp.status_code < 300, "deposits": resp.json() if resp.status_code < 300 else resp.text}

# ---------- Webhook: Withdraw ----------
@app.post("/webhooks/withdraw")
async def handle_withdraw_request(withdraw: Withdrawal):
    """Receive withdrawal request and store in Supabase."""
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
            headers={**sb_headers(), "Prefer": "return=representation"},
            json=record,
            timeout=20,
        )
    return {"ok": resp.status_code < 300, "data": resp.json() if resp.status_code < 300 else resp.text}

# ---------- List Withdrawals ----------
@app.get("/withdrawals")
async def list_withdrawals():
    """Return all withdrawals from Supabase."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{SUPABASE_URL}/rest/v1/withdrawals?select=*",
            headers=sb_headers(),
            timeout=20,
        )
    return {"ok": resp.status_code < 300, "withdrawals": resp.json() if resp.status_code < 300 else resp.text}

# ---------- VALR Deposits ----------
@app.get("/valr/deposits")
async def get_valr_deposits():
    """
    Fetch ZAR deposit history from VALR (read-only),
    store results in Supabase, and match Stitch deposits by amount.
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

        # Fetch deposits from VALR
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"https://api.valr.com{path}", headers=headers, timeout=30)
        if resp.status_code >= 300:
            return {"ok": False, "error": f"VALR HTTP {resp.status_code}: {resp.text}"}

        valr_data = resp.json() or []

        # Fetch existing Stitch deposits
        async with httpx.AsyncClient() as client:
            stitch_resp = await client.get(
                f"{SUPABASE_URL}/rest/v1/deposits?select=client_id,amount_zar,stitch_txid,timestamp",
                headers=sb_headers(),
                timeout=20,
            )
        stitch_data = stitch_resp.json() if stitch_resp.status_code < 300 else []

        # Prepare VALR records + match
        matched_records = []
        for v in valr_data:
            amount = float(v.get("amount") or 0)
            created = v.get("createdAt")
            status = v.get("status")
            desc = v.get("description", "")
            matched_client = None
            matched_txid = None

            for s in stitch_data:
                if abs(float(s["amount_zar"]) - amount) <= 5:
                    matched_client = s["client_id"]
                    matched_txid = s["stitch_txid"]
                    break

            matched_records.append({
                "valr_id": v.get("id"),
                "currency": v.get("currency"),
                "amount": amount,
                "status": status,
                "created_at": created,
                "description": desc,
                "client_id": matched_client,
                "matched_stitch_txid": matched_txid,
            })

        # Upsert into Supabase table "valr_deposits"
        async with httpx.AsyncClient() as client:
            insert = await client.post(
                f"{SUPABASE_URL}/rest/v1/valr_deposits",
                headers={**sb_headers(), "Prefer": "resolution=merge-duplicates"},
                json=matched_records,
                timeout=30,
            )

        return {
            "ok": True,
            "inserted": len(matched_records),
            "valr_deposits": matched_records
        }

    except Exception as e:
        return {"ok": False, "error": str(e)}

# ---------- Health Check ----------
@app.get("/")
def health_check():
    """Basic health check endpoint."""
    return {"status": "Netzer backend live (Supabase + VALR matching enabled)"}

@app.post("/nav/calculate")
async def calculate_nav(data: dict):
    """
    Calculate client NAV and record fee breakdown in Supabase.
    ----------------------------------------------------------------
    JSON Body:
    {
      "client_id": "string",            # required
      "deposit_zar": float,             # required, client deposit
      "zar_to_usdt_rate": float,        # required, exchange rate
      "trade_fee_rate": float = 0.001,  # optional, default 0.1%
      "withdrawal_fee_usdt": float = 1, # optional, default 1 USDT
      "fund_model": "fee_adjusted"      # optional, 'buffer' or 'fee_adjusted'
    }
    ----------------------------------------------------------------
    Returns NAV details + logs fee to Supabase.
    """

    try:
        # --- Input parsing with defaults ---
        cid: str = data["client_id"]
        deposit_zar: float = float(data["deposit_zar"])
        rate: float = float(data["zar_to_usdt_rate"])
        trade_fee_rate: float = float(data.get("trade_fee_rate", 0.001))
        withdrawal_fee_usdt: float = float(data.get("withdrawal_fee_usdt", 1))
        model: str = data.get("fund_model", "fee_adjusted")

        # --- Core NAV math ---
        gross_usdt = deposit_zar / rate               # ZAR→USDT conversion
        trade_fee_usdt = gross_usdt * trade_fee_rate  # trading fee in USDT

        if model == "buffer":
            # You (Netzer) absorb fees; client invests full amount
            nav_units = gross_usdt
        else:
            # Client invests net of fees
            nav_units = gross_usdt - trade_fee_usdt - withdrawal_fee_usdt

        # --- Record fee data in Supabase ---
        record = {
            "client_id": cid,
            "trade_fee": round(trade_fee_usdt, 6),
            "withdrawal_fee": round(withdrawal_fee_usdt, 6),
            "fund_model": model,
        }

        async with httpx.AsyncClient() as client:
            await client.post(
                f"{SUPABASE_URL}/rest/v1/fees",
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=representation",
                },
                json=record,
                timeout=20,
            )

        # --- Return NAV summary ---
        return {
            "ok": True,
            "client_id": cid,
            "fund_model": model,
            "gross_usdt": round(gross_usdt, 6),
            "nav_units": round(nav_units, 6),
            "trade_fee_usdt": round(trade_fee_usdt, 6),
            "withdrawal_fee_usdt": round(withdrawal_fee_usdt, 6),
            "total_fees_usdt": round(trade_fee_usdt + withdrawal_fee_usdt, 6),
        }

    except Exception as e:
        return {"ok": False, "error": str(e)}

