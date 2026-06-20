"""Payments API — FastAPI app instrumented with Argus SDK.

A fintech payments service instrumented with Argus for observability.
Provides payment processing, account management, compliance screening,
and transfer initiation endpoints.
"""

import asyncio
import logging
import os
import random
import shutil
import subprocess

import argus
from argus.decorators import trace
from argus.exceptions import install as install_exception_hook
from argus.logger import ArgusHandler
from argus.middleware.fastapi import ArgusMiddleware

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Initialize Argus SDK
argus.init(
    server_url=os.getenv("ARGUS_URL", "http://localhost:7600"),
    service_name=os.getenv("SERVICE_NAME", "payments-api"),
    runtime_metrics=True,
    auto_instrument=True,
)
install_exception_hook()

# Add Argus log handler
handler = ArgusHandler()
logging.getLogger().addHandler(handler)

app = FastAPI(title="Payments API")
app.add_middleware(ArgusMiddleware)

logger = logging.getLogger("payments-api")

PORT = int(os.getenv("PORT", "8000"))

# ---------------------------------------------------------------------------
# Merchant account data
# ---------------------------------------------------------------------------
MERCHANTS = {
    "acct_1001": {
        "account_id": "acct_1001",
        "business_name": "Coastal Coffee Roasters",
        "status": "active",
        "currency": "USD",
        "account_type": "merchant",
        "created_at": "2024-08-14T09:22:00Z",
        "risk_tier": "low",
    },
    "acct_1002": {
        "account_id": "acct_1002",
        "business_name": "Nimbus Cloud Hosting",
        "status": "active",
        "currency": "USD",
        "account_type": "merchant",
        "created_at": "2024-06-02T14:35:00Z",
        "risk_tier": "low",
    },
    "acct_1003": {
        "account_id": "acct_1003",
        "business_name": "Verdant Meal Prep",
        "status": "active",
        "currency": "EUR",
        "account_type": "merchant",
        "created_at": "2024-11-20T11:10:00Z",
        "risk_tier": "medium",
    },
    "acct_1004": {
        "account_id": "acct_1004",
        "business_name": "Atlas Freight Logistics",
        "status": "active",
        "currency": "USD",
        "account_type": "enterprise",
        "created_at": "2023-12-05T08:00:00Z",
        "risk_tier": "low",
    },
    "acct_1005": {
        "account_id": "acct_1005",
        "business_name": "Pixel & Press Design Studio",
        "status": "active",
        "currency": "GBP",
        "account_type": "merchant",
        "created_at": "2025-01-18T16:45:00Z",
        "risk_tier": "low",
    },
}

# ---------------------------------------------------------------------------
# Chaos state — supports multiple active modes simultaneously
# ---------------------------------------------------------------------------
_chaos_modes: set[str] = set()


# ---------------------------------------------------------------------------
# Ops simulation endpoints (hidden from demo — triggered before recording)
# ---------------------------------------------------------------------------


@app.post("/_ops/simulate/db-failure")
async def ops_db_failure():
    """Activate database-down chaos mode. DB-dependent endpoints fail."""
    _chaos_modes.add("down")
    logger.warning("OPS: database failure simulation ACTIVATED")
    return {"simulation": "db-failure", "active": sorted(_chaos_modes)}


@app.post("/_ops/simulate/degraded")
async def ops_degraded():
    """Activate degraded performance mode. Endpoints get extra latency."""
    _chaos_modes.add("slow")
    logger.warning("OPS: degraded performance simulation ACTIVATED")
    return {"simulation": "degraded", "active": sorted(_chaos_modes)}


@app.post("/_ops/simulate/compromised")
async def ops_compromised():
    """Spawn a fake xmrig process for security demo."""
    xmrig_path = "/tmp/xmrig"

    try:
        result = subprocess.run(
            ["pgrep", "-x", "xmrig"], capture_output=True, text=True,
        )
        if result.returncode == 0:
            pids = result.stdout.strip()
            return {"simulation": "compromised", "status": "already_running", "pids": pids}
    except Exception:
        pass

    sleep_bin = shutil.which("sleep")
    if not sleep_bin:
        return JSONResponse(
            status_code=500,
            content={"error": "Cannot find 'sleep' binary to create fake xmrig"},
        )

    if not os.path.exists(xmrig_path):
        shutil.copy2(sleep_bin, xmrig_path)
        os.chmod(xmrig_path, 0o755)

    proc = subprocess.Popen(
        [xmrig_path, "infinity"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    _chaos_modes.add("vuln")
    logger.warning("OPS: xmrig process spawned (PID %d)", proc.pid)
    return {"simulation": "compromised", "pid": proc.pid, "active": sorted(_chaos_modes)}


@app.post("/_ops/simulate/recover")
async def ops_recover():
    """Deactivate all simulation modes."""
    prev = sorted(_chaos_modes)
    _chaos_modes.clear()
    logger.info("OPS: all simulations cleared (were: %s)", prev)
    return {"simulation": "recovered", "previous": prev}


@app.get("/_ops/simulate/status")
async def ops_status():
    """Return currently active simulation modes."""
    return {"active": sorted(_chaos_modes)}


# ---------------------------------------------------------------------------
# Application endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    """Health check — always responds, even during simulated failures."""
    return {
        "status": "ok",
        "service": os.getenv("SERVICE_NAME", "payments-api"),
        "version": "2.4.1",
    }


@app.get("/v1/accounts/{account_id}")
@trace("get_account")
async def get_account(account_id: str):
    """Fetch a merchant account by ID."""
    logger.info("Account lookup: %s", account_id)

    # Chaos: degraded performance
    if "slow" in _chaos_modes:
        delay = random.uniform(2.0, 5.0)
        logger.warning("Connection pool wait exceeded 2000ms (current active: 19/20)")
        argus.add_breadcrumb("infra", f"Connection pool wait: {delay:.1f}s")
        await asyncio.sleep(delay)

    # Chaos: database down
    if "down" in _chaos_modes:
        err = ConnectionError("could not connect to pg-primary.internal:5432 — connection refused")
        logger.error("DatabaseError: %s", err)
        argus.capture_exception(err)
        argus.event("dependency_error", {
            "dependency": "pg-primary.internal:5432",
            "type": "postgres",
            "error": "connection refused",
            "pool_active": 0,
            "pool_max": 20,
        })
        return JSONResponse(
            status_code=503,
            content={"error": "DatabaseError: could not connect to pg-primary.internal:5432 — connection refused"},
        )

    # Lookup from merchant data
    merchant = MERCHANTS.get(account_id)
    if not merchant:
        return JSONResponse(
            status_code=404,
            content={"error": f"Account {account_id} not found"},
        )

    await asyncio.sleep(random.uniform(0.01, 0.05))
    argus.event("account_lookup", {"account_id": account_id, "business_name": merchant["business_name"], "lookup_ms": random.randint(8, 45)})
    return merchant


@app.post("/v1/payments/refund")
@trace("process_refund")
async def process_refund(request: Request):
    """Process a payment refund — always fails (original txn not found)."""
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    txn_id = body.get("transaction_id", f"txn_{random.choice(['a8f3k', 'b2m9p', 'c4x7q', 'd1n6r'])}")
    amount = body.get("amount", round(random.uniform(10.0, 250.0), 2))

    logger.info("Refund request: %s for $%.2f", txn_id, amount)
    argus.add_breadcrumb("refund", "Looking up original transaction", {"transaction_id": txn_id})

    try:
        raise ValueError(f"Original transaction {txn_id} not found or already refunded")
    except ValueError as e:
        logger.error("Refund failed: %s", e)
        argus.capture_exception(e)
        return JSONResponse(status_code=400, content={"error": str(e), "code": "REFUND_NOT_FOUND"})


@app.get("/v1/compliance/screen")
@trace("compliance_screening")
async def compliance_screen():
    """AML/KYC compliance screening — naturally slow (1-3s)."""
    logger.info("Compliance screening initiated")

    # Chaos: degraded performance (becomes very slow)
    if "slow" in _chaos_modes:
        delay = random.uniform(8.0, 15.0)
        logger.warning("Watchlist DB response time critical: %dms", int(delay * 1000))
        argus.add_breadcrumb("infra", f"Watchlist DB latency spike: {delay:.1f}s")
        await asyncio.sleep(delay)

    # Chaos: database down
    if "down" in _chaos_modes:
        err = ConnectionError("cannot query watchlist database — all retries exhausted (3/3)")
        logger.error("ComplianceError: %s", err)
        argus.capture_exception(err)
        return JSONResponse(
            status_code=503,
            content={"error": "ComplianceError: cannot query watchlist database — all retries exhausted (3/3)"},
        )

    # Natural latency for compliance checks
    delay = random.uniform(1.0, 3.0)
    await asyncio.sleep(delay)

    screening_id = f"scr_{random.randbytes(3).hex()}"
    risk_score = random.randint(2, 25)
    argus.event("compliance_screened", {
        "screening_id": screening_id,
        "risk_score": risk_score,
        "duration_ms": int(delay * 1000),
    })

    return {
        "screening_id": screening_id,
        "status": "clear",
        "risk_score": risk_score,
        "checks_completed": ["ofac", "pep", "adverse_media"],
        "check_duration_ms": int(delay * 1000),
    }


@app.post("/v1/transfers/initiate")
@trace("initiate_transfer")
async def initiate_transfer(request: Request):
    """Initiate a fund transfer — validates account, checks balance, initiates."""
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    from_account = body.get("from_account", "acct_1001")
    to_account = body.get("to_account", "acct_1002")
    amount = body.get("amount", round(random.uniform(50.0, 5000.0), 2))
    currency = body.get("currency", "USD")

    logger.info("Transfer: %s -> %s, $%.2f %s", from_account, to_account, amount, currency)

    # Chaos: degraded performance
    if "slow" in _chaos_modes:
        delay = random.uniform(4.0, 8.0)
        logger.warning("Balance verification slow: replica lag detected (%dms)", int(delay * 1000))
        argus.add_breadcrumb("infra", f"Read replica lag: {delay:.1f}s")
        await asyncio.sleep(delay)

    # Chaos: database down
    if "down" in _chaos_modes:
        err = ConnectionError("cannot verify available balance — read replica unreachable")
        logger.error("BalanceLookupError: %s", err)
        argus.capture_exception(err)
        argus.event("dependency_error", {
            "dependency": "pg-replica.internal:5432",
            "type": "postgres",
            "error": "read replica unreachable",
        })
        return JSONResponse(
            status_code=503,
            content={"error": "BalanceLookupError: cannot verify available balance — read replica unreachable"},
        )

    # Step 1: Validate sender account (internal call)
    base = f"http://localhost:{PORT}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{base}/v1/accounts/{from_account}")
        sender = resp.json()

    # Step 2: Simulate balance check
    await asyncio.sleep(random.uniform(0.02, 0.08))

    transfer_id = f"tfr_{random.randbytes(4).hex()}"
    argus.event("transfer_initiated", {
        "transfer_id": transfer_id,
        "from_account": from_account,
        "to_account": to_account,
        "amount": amount,
        "currency": currency,
    })

    return {
        "transfer_id": transfer_id,
        "status": "pending",
        "from_account": from_account,
        "to_account": to_account,
        "amount": amount,
        "currency": currency,
        "sender": sender.get("business_name", from_account),
    }


@app.post("/v1/payments/charge")
@trace("process_charge")
async def process_charge(request: Request):
    """Process a payment charge — breadcrumbs through payment flow, fails at card network."""
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    amount = body.get("amount", round(random.uniform(15.0, 500.0), 2))
    currency = body.get("currency", "USD")
    source = body.get("source", f"tok_visa_{random.randint(1000, 9999)}")
    merchant_id = body.get("merchant_id", "mch_8291")

    logger.info("Charge: $%.2f %s via %s for %s", amount, currency, source, merchant_id)

    # Chaos: degraded performance
    if "slow" in _chaos_modes:
        delay = random.uniform(5.0, 12.0)
        logger.warning("Card network response degraded: %dms", int(delay * 1000))
        argus.add_breadcrumb("infra", f"Card network latency: {delay:.1f}s")
        await asyncio.sleep(delay)

    # Chaos: database down — gets partway through, fails at persistence
    if "down" in _chaos_modes:
        argus.add_breadcrumb("payment", "Validated merchant credentials (cached)", {"merchant_id": merchant_id})
        await asyncio.sleep(0.01)
        argus.add_breadcrumb("payment", "Fraud score computed", {"score": 12, "threshold": 75, "decision": "allow"})
        await asyncio.sleep(0.01)

        err = ConnectionError("failed to write to transactions table — database unavailable")
        logger.error("TransactionPersistError: %s", err)
        argus.add_breadcrumb("payment", "Persisting transaction record")
        argus.capture_exception(err)
        return JSONResponse(
            status_code=503,
            content={"error": "TransactionPersistError: failed to write to transactions table — database unavailable"},
        )

    argus.add_breadcrumb("payment", "Validated merchant credentials", {"merchant_id": merchant_id, "status": "active"})
    await asyncio.sleep(0.01)

    argus.add_breadcrumb("payment", "Fraud score computed", {"score": 12, "threshold": 75, "decision": "allow"})
    await asyncio.sleep(0.01)

    network = random.choice(["visa", "mastercard"])
    argus.add_breadcrumb("payment", "Submitting to card network", {"network": network, "amount": amount, "currency": currency})

    try:
        raise RuntimeError(f"Card network ({network.title()}) did not respond within 30000ms")
    except RuntimeError as e:
        logger.error("GatewayTimeoutError: %s", e)
        argus.capture_exception(e)
        return JSONResponse(status_code=504, content={"error": f"GatewayTimeoutError: {e}", "code": "GATEWAY_TIMEOUT"})


@app.get("/v1/rates/convert")
@trace("fetch_exchange_rate")
async def fetch_exchange_rate():
    """Fetch live exchange rates from upstream FX provider."""
    logger.info("Fetching exchange rates from upstream provider")

    # Chaos: degraded performance (but still works — no DB needed)
    if "slow" in _chaos_modes:
        delay = random.uniform(3.0, 6.0)
        logger.warning("Upstream FX provider latency spike: %dms", int(delay * 1000))
        argus.add_breadcrumb("infra", f"FX provider latency: {delay:.1f}s")
        await asyncio.sleep(delay)

    # Rate conversion always works even when DB is down (no DB dependency)
    async with httpx.AsyncClient() as client:
        resp = await client.get("https://jsonplaceholder.typicode.com/todos/1")
        data = resp.json()

    rate = round(random.uniform(0.82, 0.95), 4)
    argus.event("exchange_rate_fetched", {"pair": "USD/EUR", "rate": rate, "provider": "ecb"})

    return {
        "pair": "USD/EUR",
        "rate": rate,
        "provider": "ecb",
        "timestamp": "2025-03-21T14:30:00Z",
        "upstream_ref": data.get("id"),
    }


@app.post("/v1/payments/authorize")
@trace("authorize_payment")
async def authorize_payment(request: Request):
    """Authorize a payment — generates varied realistic payment errors."""
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    amount = body.get("amount", round(random.uniform(5.0, 500.0), 2))
    card_last4 = body.get("card_last4", str(random.randint(1000, 9999)))
    merchant_id = body.get("merchant_id", f"mch_{random.randint(1000, 9999)}")

    logger.info("Authorization: $%.2f for %s (card ending %s)", amount, merchant_id, card_last4)

    # Chaos: degraded performance
    if "slow" in _chaos_modes:
        delay = random.uniform(3.0, 7.0)
        logger.warning("Issuing bank response degraded: %dms", int(delay * 1000))
        argus.add_breadcrumb("infra", f"Issuing bank latency: {delay:.1f}s")
        await asyncio.sleep(delay)

    # Chaos: database down
    if "down" in _chaos_modes:
        err = ConnectionError("cannot record authorization hold — ledger database unavailable")
        logger.error("LedgerWriteError: %s", err)
        argus.capture_exception(err)
        return JSONResponse(
            status_code=503,
            content={"error": "LedgerWriteError: cannot record authorization hold — ledger database unavailable"},
        )

    error_types = [
        (ValueError, f"Card number failed Luhn check: invalid card ending in {card_last4}"),
        (TimeoutError, "Issuing bank did not respond: timeout after 15000ms (BIN: 431940)"),
        (PermissionError, f"Transaction declined: insufficient funds (available: $42.18, requested: ${amount:.2f})"),
        (ConnectionError, "Payment processor connection refused: stripe-proxy.internal:8443"),
        (RuntimeError, "Duplicate idempotency key: idem_9xk2m — original txn in terminal state"),
    ]
    err_cls, msg = random.choice(error_types)
    argus.add_breadcrumb("authorization", f"Processing card ending {card_last4}", {"merchant_id": merchant_id, "amount": amount})
    argus.add_breadcrumb("authorization", f"Auth check: {err_cls.__name__}")

    try:
        raise err_cls(msg)
    except Exception as e:
        logger.error("Authorization failed: %s: %s", type(e).__name__, e)
        argus.capture_exception(e)
        return JSONResponse(status_code=400, content={"error": str(e), "type": type(e).__name__, "code": "AUTH_FAILED"})


# --- Background traffic simulator ---


async def _traffic_simulator():
    """Generate background traffic to keep telemetry flowing."""
    endpoints = [
        ("GET", "/health", 8),
        ("GET", "/v1/accounts/acct_1001", 6),
        ("GET", "/v1/accounts/acct_1002", 4),
        ("POST", "/v1/payments/charge", 5),
        ("POST", "/v1/payments/authorize", 4),
        ("POST", "/v1/transfers/initiate", 3),
        ("GET", "/v1/rates/convert", 3),
        ("GET", "/v1/compliance/screen", 2),
        ("POST", "/v1/payments/refund", 2),
    ]
    weighted = []
    for method, path, weight in endpoints:
        weighted.extend([(method, path)] * weight)

    base = f"http://localhost:{PORT}"

    await asyncio.sleep(5)
    logger.info("Traffic simulator started")

    while True:
        try:
            method, path = random.choice(weighted)
            async with httpx.AsyncClient() as client:
                if method == "GET":
                    await client.get(f"{base}{path}", timeout=30.0)
                else:
                    await client.post(f"{base}{path}", timeout=30.0)
        except Exception:
            pass

        delay = random.uniform(10, 45)
        await asyncio.sleep(delay)


@app.on_event("startup")
async def startup():
    asyncio.create_task(_traffic_simulator())


@app.on_event("shutdown")
async def shutdown():
    argus.shutdown()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
