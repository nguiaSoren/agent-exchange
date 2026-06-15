"""x402 spike — SELLER (resource server).

A FastAPI server with ONE paid endpoint (`GET /audit`) priced at $0.001 in test
USDC on Base Sepolia, settled via the free public x402.org facilitator. This is
the seller half of the "can a coin move" spike. Run it, leave it running,
then run `x402_buyer.py` in another terminal.

Run:
    cd agent-exchange
    uv pip install --python .venv "x402[fastapi]" uvicorn python-dotenv
    .venv/bin/python spikes/x402_seller.py
"""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI

from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.schemas import Network
from x402.server import x402ResourceServer

load_dotenv()

EVM_NETWORK: Network = os.getenv("X402_NETWORK", "eip155:84532")  # Base Sepolia
PAY_TO = os.environ["SELLER_PAYTO_ADDRESS"]
FACILITATOR_URL = os.getenv("X402_FACILITATOR_URL", "https://x402.org/facilitator")

facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=FACILITATOR_URL))
server = x402ResourceServer(facilitator)
server.register(EVM_NETWORK, ExactEvmServerScheme())

app = FastAPI(title="Agent Exchange — x402 seller spike")

routes: dict[str, RouteConfig] = {
    "GET /audit": RouteConfig(
        accepts=[
            PaymentOption(
                scheme="exact",
                pay_to=PAY_TO,
                price="$0.001",
                network=EVM_NETWORK,
            ),
        ],
        mime_type="application/json",
        description="Spike: a $0.001 paid endpoint (stands in for a worker's deliverable).",
    ),
}
app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)


@app.get("/audit")
async def audit() -> dict[str, Any]:
    # Reached ONLY after the facilitator verifies payment.
    return {
        "ok": True,
        "deliverable": "audit complete — 0 risky clauses (spike stub)",
        "note": "you paid $0.001 in test USDC for this — the coin moved on Base Sepolia",
    }


if __name__ == "__main__":
    import uvicorn

    print(f"x402 SELLER up · payTo={PAY_TO} · network={EVM_NETWORK} · facilitator={FACILITATOR_URL}")
    print("GET http://127.0.0.1:4021/audit  (price $0.001) — leave running; now run spikes/x402_buyer.py")
    uvicorn.run(app, host="127.0.0.1", port=4021)
