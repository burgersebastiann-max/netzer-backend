# Netzer Flow MVP (FastAPI)

Client ZAR -> Company Bank (Stitch) -> VALR (buy USDT) -> Bybit (whitelisted)

## What this does
- Receives a **Stitch webhook** when a client deposits ZAR
- (Placeholder) initiates a payout to VALR business bank
- Receives a **VALR webhook** confirming ZAR deposit
- Places a **market order** ZAR->USDT (simulated call, recorded in DB)
- Initiates a **VALR withdrawal** of USDT to **whitelisted** Bybit address (simulated)
- Receives a **Bybit webhook** confirming deposit to Bybit
- Stores full **audit trail** in SQLite

## Files
- `app.py` — FastAPI app with routes and flow
- `requirements.txt` — pip deps
- `netzer.db` — SQLite auto-created

## Run (local)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export VALR_API_KEY=... VALR_API_SECRET=...
export BYBIT_API_KEY=... BYBIT_API_SECRET=...
export STITCH_WEBHOOK_SECRET=...
export VALR_WITHDRAW_WHITELIST_ID=BYBIT_USDT_TRC20
uvicorn app:app --reload
```

## Test (quick)
```bash
# Simulate a Stitch deposit
curl -X POST http://127.0.0.1:8000/webhooks/stitch \
  -H "Content-Type: application/json" \
  -d '{"client_id":"A123","amount_zar":10000,"stitch_txid":"STCH-001"}'

# Simulate VALR confirming ZAR deposit
curl -X POST http://127.0.0.1:8000/webhooks/valr/zar-deposit \
  -H "Content-Type: application/json" \
  -d '{"valr_deposit_id":"VALRDEP-1","amount_zar":10000,"credited_at":"2025-10-17 10:00:00"}'

# Simulate VALR sending withdrawal update (broadcasted)
curl -X POST http://127.0.0.1:8000/webhooks/valr/withdrawal \
  -H "Content-Type: application/json" \
  -d '{"withdraw_id":"VALRW-1","txhash":"0xabc123...","status":"broadcasted"}'

# Simulate Bybit confirming receipt
curl -X POST http://127.0.0.1:8000/webhooks/bybit/deposit \
  -H "Content-Type: application/json" \
  -d '{"bybit_deposit_id":"BYB-DEP-001","asset":"USDT","amount":524.18,"credited_at":"2025-10-17 10:10:00"}'

# Inspect
curl http://127.0.0.1:8000/deposits
curl http://127.0.0.1:8000/exchanges
curl http://127.0.0.1:8000/transfers
curl http://127.0.0.1:8000/audit
```
## Important
- Replace placeholder API calls with real **Stitch/VALR/Bybit** endpoints & signatures.
- Add HMAC verification for all webhooks.
- Enforce **whitelist-only** withdrawals on VALR.
- Add retries / idempotency keys on all external calls.
- Split client funds using sub-accounts or metadata in your own ledger.
