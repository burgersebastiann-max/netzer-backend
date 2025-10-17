from fastapi import FastAPI, Request
from supabase import create_client, Client
from datetime import datetime
import os

# Initialize FastAPI
app = FastAPI(title="Netzer Backend", version="1.0")

# Connect to Supabase using environment variables (from Render)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# -----------------------------------------------------
# 1️⃣ Deposit Webhook - Record client deposits
# -----------------------------------------------------
@app.post("/webhooks/stitch")
async def handle_stitch_webhook(request: Request):
    """
    Handles incoming deposit webhooks (e.g., from Stitch).
    Saves deposit info into the Supabase 'deposits' table.
    """
    data = await request.json()

    client_id = data.get("client_id")
    amount_zar = data.get("amount_zar")
    stitch_txid = data.get("stitch_txid")

    # Basic validation
    if not all([client_id, amount_zar, stitch_txid]):
        return {"ok": False, "error": "Missing required fields"}

    record = {
        "client_id": client_id,
        "amount_zar": amount_zar,
        "stitch_txid": stitch_txid,
        "timestamp": datetime.utcnow().isoformat(),
        "status": "completed"
    }

    try:
        response = supabase.table("deposits").insert(record).execute()
        return {"ok": True, "data": response.data}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# -----------------------------------------------------
# 2️⃣ Fetch All Deposits - For dashboard/admin view
# -----------------------------------------------------
@app.get("/deposits")
def list_deposits():
    """
    Returns all deposit records from Supabase.
    """
    try:
        response = supabase.table("deposits").select("*").order("timestamp", desc=True).execute()
        return {"ok": True, "deposits": response.data}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# -----------------------------------------------------
# 3️⃣ Health Check - For uptime monitoring
# -----------------------------------------------------
@app.get("/")
def health_check():
    """
    Basic health check endpoint.
    """
    return {"status": "Netzer backend is live and connected."}
