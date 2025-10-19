# routes_valr_trade.py
from fastapi import APIRouter
import os, time, json, hmac, hashlib, httpx
from typing import Dict, Any
from datetime import datetime

router = APIRouter()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE = os.getenv("SUPABASE_SERVICE_ROLE") or os.getenv("SUPABASE_KEY") or ""
VALR_API_KEY = os.getenv("VALR_API_KEY", "")
VALR_API_SECRET = os.getenv("VALR_API_SECRET", "")
PAIR = "USDTZAR"

def sb_headers() -> Dict[str, str]:
    return {
        "apikey": SUPABASE_SERVICE_ROLE,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE}",
        "Content-Type": "application/json",
    }

def valr_sign(method: str, path: str, body: str = "") -> Dict[str, str]:
    ts = str(int(time.time() * 1000))
    payload = ts + method.upper() + path + body
    sig = hmac.new(VALR_API_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha512).hexdigest()
    return {"X-VALR-API-KEY": VALR_API_KEY, "X-VALR-SIGNATURE": sig, "X-VALR-TIMESTAMP": ts}

async def valr_get(client: httpx.AsyncClient, path: str):
    headers = valr_sign("GET", path, "")
    r = await client.get("https://api.valr.com" + path, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()

async def valr_post(client: httpx.AsyncClient, path: str, json_body: Dict[str, Any]):
    body = json.dumps(json_body, separators=(",", ":"))
    headers = valr_sign("POST", path, body)
    headers["Content-Type"] = "application/json"
    r = await client.post("https://api.valr.com" + path, headers=headers, content=body, timeout=30)
    r.raise_for_status()
    return r.json() if r.content else {}

async def insert_execution(rec: Dict[str, Any]):
    async with httpx.AsyncClient() as c:
        r = await c.post(
            f"{SUPABASE_URL}/rest/v1/executions",
            headers={**sb_headers(), "Prefer": "return=representation"},
            json=rec,
            timeout=30,
        )
        ok = r.status_code < 300
        try:
            data = r.json() if ok else {"error": r.text}
        except Exception:
            data = {"raw": r.text}
        return {"ok": ok, "resp": data}

@router.post("/valr/auto-trade")
async def auto_trade():
    if not (SUPABASE_URL and SUPABASE_SERVICE_ROLE and VALR_API_KEY and VALR_API_SECRET):
        return {"ok": False, "error": "Missing env vars"}

    async with httpx.AsyncClient() as client:
        balances = await valr_get(client, "/v1/account/balances")

        def avail(symbol: str) -> float:
            for b in balances:
                if b.get("currency") == symbol:
                    return float(b.get("available") or 0)
            return 0.0

        zar = avail("ZAR")
        usdt = avail("USDT")
        MIN_ZAR, MIN_USDT = 10.0, 1.0
        side, payload, resp = None, None, {}

        if zar >= MIN_ZAR:
            side = "BUY"
            payload = {"pair": PAIR, "side": "BUY", "quoteAmount": zar, "timeInForce": "IOC"}
            resp = await valr_post(client, "/v1/orders/market", payload)
        elif usdt >= MIN_USDT:
            side = "SELL"
            payload = {"pair": PAIR, "side": "SELL", "baseAmount": usdt, "timeInForce": "IOC"}
            resp = await valr_post(client, "/v1/orders/market", payload)
        else:
            return {"ok": True, "action": "NOOP", "zar": zar, "usdt": usdt}

        order_id = resp.get("id") or resp.get("orderId") or f"VALR-{int(time.time())}"
        record = {
            "client_id": "auto",
            "side": side,
            "pair": PAIR,
            "zar_amount": zar if side == "BUY" else None,
            "usdt_amount": usdt if side == "SELL" else None,
            "exchange_order_id": order_id,
            "status": "SUBMITTED",
            "created_at": datetime.utcnow().isoformat(),
        }
        ins = await insert_execution(record)

        return {
            "ok": True,
            "side": side,
            "zar_before": zar,
            "usdt_before": usdt,
            "order_payload": payload,
            "exchange_response": resp,
            "supabase_insert": ins,
        }

@router.get("/executions/recent")
async def recent(limit: int = 20):
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE:
        return {"ok": False, "error": "Missing SUPABASE env vars"}
    async with httpx.AsyncClient() as c:
        r = await c.get(
            f"{SUPABASE_URL}/rest/v1/executions?select=*&order=created_at.desc&limit={limit}",
            headers=sb_headers(),
            timeout=30,
        )
    ok = r.status_code < 300
    data = r.json() if ok else {"error": r.text}
    return {"ok": ok, "executions": dat
