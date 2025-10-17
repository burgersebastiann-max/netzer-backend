from fastapi import FastAPI, Request
import os, httpx
from datetime import datetime

app = FastAPI(title="Netzer Backend", version="1.1")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# -----------------------------------------------------
# POST /webhooks/stitch  →  insert deposit record
# -----------------------------------------------------
from fastapi import FastAPI, Request
from pydantic import BaseModel
import os, httpx
from datetime import datetime

app = FastAPI(title="Netzer Backend", version="1.1")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# --- NEW: define the data model for request body ---
class Deposit(BaseModel):
    client_id: str
    amount_zar: float
    stitch_txid: str

# -----------------------------------------------------
# POST /webhooks/stitch  →  insert deposit record
# -----------------------------------------------------
@app.post("/webhooks/stitch")
async def handle_stitch_webhook(deposit: Deposit):
    record = {
        "client_id": deposit.client_id,
        "amount_zar": deposit.amount_zar,
        "stitch_txid": deposit.stitch_txid,
        "timestamp": datetime.utcnow().isoformat(),
        "status": "completed"
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{SUPABASE_URL}/rest/v1/deposits",
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=representation"
                },
                json=record,
                timeout=20
            )
        if resp.status_code < 300:
            return {"ok": True, "data": resp.json()}
        else:
            return {"ok": False, "error": resp.text}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# -----------------------------------------------------
# GET /deposits  →  list all deposits
# -----------------------------------------------------
@app.get("/deposits")
async def list_deposits():
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{SUPABASE_URL}/rest/v1/deposits?select=*",
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}"
                },
                timeout=20
            )
        if resp.status_code < 300:
            return {"ok": True, "deposits": resp.json()}
        else:
            return {"ok": False, "error": resp.text}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# -----------------------------------------------------
# Health check
# -----------------------------------------------------
@app.get("/")
def health_check():
    return {"status": "Netzer backend live (HTTP Supabase mode)"}
