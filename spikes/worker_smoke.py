"""Worker live smoke — run a real worker on AI/ML API (and optionally Featherless),
showing the cross-model substrate + the instrumentation that feeds /metrics.

Needs AIMLAPI_API_KEY in .env. Pick a model that AI/ML API actually serves
(verify against their model list / docs/CAPABILITIES); override with
AIMLAPI_MODEL. Featherless is exercised too if FEATHERLESS_API_KEY + FEATHERLESS_MODEL
are set.

Run: cd agent-exchange && .venv/bin/python spikes/worker_smoke.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv

from agent_exchange.core import CompletionResult, make_backend
from agent_exchange.metrics import StageTimings, monotonic_ns, usdc
from agent_exchange.workers import Worker

load_dotenv()

LIABILITY_PROMPT = (
    "You are a contract-audit specialist for liability clauses. Given a contract "
    "excerpt, list any clause that caps, waives, or limits liability. Be terse: one "
    "bullet per finding, quoting the clause. If none, say 'no liability clauses found'."
)
TASK = (
    "Audit this excerpt:\n"
    "7.1 In no event shall Vendor's aggregate liability exceed the fees paid in the "
    "twelve (12) months preceding the claim. 7.2 Vendor disclaims all indemnity for "
    "third-party IP claims."
)


def show(r: CompletionResult) -> None:
    print(f"  provider/model : {r.provider} / {r.model}")
    print(f"  finish_reason  : {r.finish_reason}  (early_termination={r.early_termination})")
    print(f"  tokens         : in={r.usage.input_tokens} out={r.usage.output_tokens} total={r.usage.total_tokens}")
    print(f"  cost_usd       : {r.cost_usd}   (None ⇒ model price not in table — fill from live pricing)")
    print(f"  latency        : {r.latency_ms:.0f} ms")
    print(f"  deliverable    :\n    " + r.text.strip().replace("\n", "\n    "))


async def run_one(provider: str, model: str) -> None:
    print(f"\n=== worker on {provider} ({model}) ===")
    worker = Worker("liability-bot", LIABILITY_PROMPT, make_backend(provider, model))
    # time the 'deliver' stage the way the marketplace will, into the /metrics schema:
    started = monotonic_ns()
    result = await worker.run(TASK, max_tokens=300)
    timings = StageTimings(started_ns=started, deliver_ns=result.return_ns)
    show(result)
    print(f"  → /metrics deliver-stage: {timings.durations_ms().get('deliver', 0):.0f} ms; "
          f"cost recorded as {result.cost_usd}")


async def main() -> None:
    ran = False
    if os.environ.get("AIMLAPI_API_KEY", "").strip():
        await run_one("aimlapi", os.getenv("AIMLAPI_MODEL", "google/gemini-3.5-flash"))
        ran = True
    else:
        print("AIMLAPI_API_KEY not set — skipping AI/ML API worker.")
    if os.environ.get("FEATHERLESS_API_KEY", "").strip() and os.getenv("FEATHERLESS_MODEL"):
        await run_one("featherless", os.environ["FEATHERLESS_MODEL"])
        ran = True
    if not ran:
        print("\nSet AIMLAPI_API_KEY (+ AIMLAPI_MODEL) in .env to exercise the live path.")


if __name__ == "__main__":
    asyncio.run(main())
