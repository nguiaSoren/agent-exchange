"""x402 spike — BUYER (client).

Calls the seller's paid endpoint. On the `402 Payment Required`, the x402 client
signs a payment with the buyer wallet (EVM_PRIVATE_KEY) and retries; the
facilitator settles it on Base Sepolia. Prints the settlement (with the on-chain
tx) — that's "the coin moved" (this exercises the REAL on-chain path).

Prereqs:
  - Seller running (spikes/x402_seller.py)
  - The BUYER address (derived from EVM_PRIVATE_KEY in .env) funded with test USDC
    from faucet.circle.com (Base Sepolia).

Run:
    cd agent-exchange
    uv pip install --python .venv "x402[httpx]" python-dotenv
    .venv/bin/python spikes/x402_buyer.py
"""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv
from eth_account import Account

from x402 import x402Client
from x402.http import x402HTTPClient
from x402.http.clients import x402HttpxClient
from x402.mechanisms.evm import EthAccountSigner
from x402.mechanisms.evm.exact.register import register_exact_evm_client

load_dotenv()

URL = os.getenv("SELLER_URL", "http://127.0.0.1:4021/audit")
EXPLORER = "https://sepolia.basescan.org/tx/"


async def main() -> None:
    account = Account.from_key(os.environ["EVM_PRIVATE_KEY"])
    print(f"x402 BUYER · wallet={account.address}")
    print(f"  → fund this address with test USDC at faucet.circle.com (Base Sepolia) if you haven't.\n")

    client = x402Client()
    register_exact_evm_client(client, EthAccountSigner(account))
    http_client = x402HTTPClient(client)

    async with x402HttpxClient(client) as http:
        # The client transparently handles 402 → sign → retry. (L4: x402's own
        # retry covers the payment dance; wrap in tenacity for raw network blips
        # when this graduates into the marketplace.)
        response = await http.get(URL)
        await response.aread()
        print(f"HTTP {response.status_code}")
        print(f"body: {response.text}")

        if response.is_success:
            settle = http_client.get_payment_settle_response(lambda name: response.headers.get(name))
            print("\n✅ PAYMENT SETTLED — a coin moved on Base Sepolia:")
            print(f"   {settle}")
            tx = getattr(settle, "transaction", None) or (settle.get("transaction") if isinstance(settle, dict) else None)
            if tx:
                print(f"   explorer: {EXPLORER}{tx}")
        else:
            print("\n⚠️  Not settled. Most likely the buyer wallet has no test USDC yet —")
            print("    fund it at faucet.circle.com (Base Sepolia) and re-run.")


if __name__ == "__main__":
    asyncio.run(main())
