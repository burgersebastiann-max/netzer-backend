# app.py
"""
Netzer Flow MVP (FastAPI)
Client ZAR -> Company Bank (Stitch webhook) -> VALR (ZAR->USDT) -> Bybit (whitelisted)
- SQLite ledger for simplicity
- Webhook endpoints for Stitch, VALR, Bybit
- Placeholder API calls for Stitch Payouts, VALR trade/withdraw, Bybit checks
NOTE: Replace placeholder API endpoints/signatures with real ones and add secret verification.
"""

import os, hmac, hashlib, time, json, sqlite3
from typing import Optional
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from pydantic import BaseModel
import httpx

DB_PATH = os.environ.get("NETZER_DB", "netzer.db")

# ======== Simple DB setup ========
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS deposits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id TEXT,
        amount_zar REAL,
        stitch_txid TEXT,
        received_at TEXT,
        status TEXT
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS exchanges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        deposit_id INTEGER,
        valr_deposit_id TEXT,
        order_id TEXT,
        pair TEXT,
        side TEXT,
        price REAL,
        base_amount REAL,
        quote_spent REAL,
        traded_at TEXT,
        status TEXT
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS transfers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        exchange_id INTEGER,
        asset TEXT,
        chain TEXT,
        amount REAL,
        valr_withdraw_id TEXT,
        txhash TEXT,
        bybit_deposit_id TEXT,
        initiated_at TEXT,
        completed_at TEXT,
        status TEXT
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event TEXT,
        ref TEXT,
        data TEXT,
        created_at TEXT
    )""")
    conn.commit()
    conn.close()

init_db()

# ======== Config / ENV ========
VALR_API_KEY     = os.environ.get("VALR_API_KEY",     "YOUR_VALR_API_KEY")
VALR_API_SECRET  = os.environ.get("VALR_API_SECRET",  "YOUR_VALR_SECRET")
BYBIT_API_KEY    = os.environ.get("BYBIT_API_KEY",    "YOUR_BYBIT_API_KEY")
BYBIT_API_SECRET = os.environ.get("BYBIT_API_SECRET", "YOUR_BYBIT_SECRET")
STITCH_WEBHOOK_SECRET = os.environ.get("STITCH_WEBHOOK_SECRET", "replace_me")
VALR_WITHDRAW_WHITELIST_ID = os.environ.get("VALR_WITHDRAW_WHITELIST_ID", "BYBIT_USDT_TRC20")

# ======== FastAPI ========
app = FastAPI(title="Netzer Flow MVP")

def sign_hmac(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()

async def post_json(url: str, headers: dict, payload: dict):
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        return r.json()

def audit(event: str, ref: str, data: dict):
    conn = db()
    conn.execute("INSERT INTO audit(event, ref, data, created_at) VALUES (?,?,?,datetime('now'))",
                 (event, ref, json.dumps(data)))
    conn.commit()
    conn.close()

# ======== Models ========
class StitchPayment(BaseModel):
    client_id: str
    amount_zar: float
    stitch_txid: str

class ValrDeposit(BaseModel):
    valr_deposit_id: str
    amount_zar: float
    credited_at: str

class ValrOrderFilled(BaseModel):
    order_id: str
    pair: str = "USDTZAR"
    side: str = "BUY"
    price: float
    base_amount: float   # USDT bought
    quote_spent: float   # ZAR spent
    filled_at: str

class ValrWithdrawalUpdate(BaseModel):
    withdraw_id: str
    txhash: Optional[str] = None
    status: str

class BybitDeposit(BaseModel):
    bybit_deposit_id: str
    asset: str = "USDT"
    amount: float
    credited_at: str

# ======== Webhooks & Flow ========
@app.post("/webhooks/stitch")
async def stitch_webhook(req: Request, payload: StitchPayment, background_tasks: BackgroundTasks):
    # TODO: verify Stitch signature header
    conn = db()
    cur = conn.cursor()
    cur.execute("INSERT INTO deposits(client_id, amount_zar, stitch_txid, received_at, status) VALUES (?,?,?,datetime('now'),'received')",
                (payload.client_id, payload.amount_zar, payload.stitch_txid))
    deposit_id = cur.lastrowid
    conn.commit(); conn.close()

    audit("stitch.deposit.received", str(deposit_id), payload.dict())

    # TODO: trigger payout to VALR via Stitch Payouts
    return {"ok": True, "deposit_id": deposit_id}

@app.post("/webhooks/valr/zar-deposit")
async def valr_zar_deposit(payload: ValrDeposit, background_tasks: BackgroundTasks):
    """VALR confirms ZAR landed. Place market order to buy USDT."""
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM deposits WHERE status='received' ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "No pending deposit found")
    deposit_id = row["id"]
    conn.execute("UPDATE deposits SET status='valr_zar' WHERE id=?", (deposit_id,))
    conn.commit(); conn.close()

    audit("valr.deposit.zar", str(deposit_id), payload.dict())

    # Trigger market order to buy USDT (simulate)
    background_tasks.add_task(place_market_buy_usdt, deposit_id, payload.amount_zar)
    return {"ok": True, "deposit_id": deposit_id}

async def place_market_buy_usdt(deposit_id: int, amount_zar: float):
    # Simulate market order
    price = 19.05
    base_amount = round(amount_zar/price, 6)
    curtime = time.strftime("%Y-%m-%d %H:%M:%S")

    conn = db()
    conn.execute("""INSERT INTO exchanges(deposit_id, valr_deposit_id, order_id, pair, side,
                  price, base_amount, quote_spent, traded_at, status)
                  VALUES (?,?,?,?,?,?,?,?,?,?)""",
                 (deposit_id, f"VALRDEP-{deposit_id}", f"VALRO-{deposit_id}", "USDTZAR", "BUY",
                  price, base_amount, amount_zar, curtime, "filled"))
    conn.commit(); conn.close()

    audit("valr.order.filled", f"{deposit_id}", {"price": price, "base": base_amount, "quote": amount_zar})

    await initiate_valr_withdraw(deposit_id, asset="USDT", chain="TRC20", amount=base_amount)

async def initiate_valr_withdraw(deposit_id: int, asset: str, chain: str, amount: float):
    withdraw_id = f"VALRW-{deposit_id}"
    conn = db()
    conn.execute("""INSERT INTO transfers(exchange_id, asset, chain, amount, valr_withdraw_id,
                    initiated_at, status)
                    VALUES ((SELECT id FROM exchanges WHERE deposit_id=?),?,?,?,?,datetime('now'),'initiated')""",
                 (deposit_id, asset, chain, amount, withdraw_id))
    conn.commit(); conn.close()
    audit("valr.withdraw.initiated", str(deposit_id), {"asset":asset,"chain":chain,"amount":amount})

@app.post("/webhooks/valr/withdrawal")
async def valr_withdrawal_update(payload: ValrWithdrawalUpdate):
    conn = db()
    conn.execute("UPDATE transfers SET txhash=?, status=? WHERE valr_withdraw_id=?",
                 (payload.txhash, payload.status, payload.withdraw_id))
    conn.commit(); conn.close()
    audit("valr.withdraw.update", payload.withdraw_id, payload.dict())
    return {"ok": True}

@app.post("/webhooks/bybit/deposit")
async def bybit_deposit(payload: BybitDeposit):
    conn = db()
    conn.execute("UPDATE transfers SET bybit_deposit_id=?, completed_at=datetime('now'), status='completed' WHERE txhash IS NOT NULL AND status!='completed'",
                 (payload.bybit_deposit_id,))
    conn.commit(); conn.close()
    audit("bybit.deposit.confirmed", payload.bybit_deposit_id, payload.dict())
    return {"ok": True}

# ======== Query endpoints ========
@app.get("/deposits")
def list_deposits():
    conn = db()
    rows = [dict(r) for r in conn.execute("SELECT * FROM deposits ORDER BY id DESC")]
    conn.close()
    return rows

@app.get("/exchanges")
def list_exchanges():
    conn = db()
    rows = [dict(r) for r in conn.execute("SELECT * FROM exchanges ORDER BY id DESC")]
    conn.close()
    return rows

@app.get("/transfers")
def list_transfers():
    conn = db()
    rows = [dict(r) for r in conn.execute("SELECT * FROM transfers ORDER BY id DESC")]
    conn.close()
    return rows

@app.get("/audit")
def list_audit():
    conn = db()
    rows = [dict(r) for r in conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 200")]
    conn.close()
    return rows

# Run: uvicorn app:app --reload
