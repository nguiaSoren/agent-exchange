"""Build the n=40 long-contract corpus for the scaled adaptive judge-spine run.

The frozen n=4 corpus (``data/eval/long_contracts.json``) is left UNTOUCHED. This generates N
DISTINCT contracts (brief × variation, temperature 0 — see ``eval/long_corpus.py``) and writes
a SEPARATE file, so the pilot keeps using the 4-doc corpus and only the big run points here via
``SCALED_CONTRACTS``.

Spend: N generations of <=2000 output tokens on a cheap model (default gpt-5.4-mini ≈ a few
dimes for N=40). LIVE call — run only with approval.

Env: OPENAI_API_KEY; CORPUS_N (default 40); CORPUS_MODEL (default gpt-5.4-mini);
     CORPUS_OUT (default data/eval/long_contracts_n40.json).
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv

from agent_exchange.core import make_backend
from agent_exchange.eval.long_corpus import (
    generate_long_contracts,
    load_long_contracts,
    save_long_contracts,
)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"))


async def _main() -> None:
    n = int(os.getenv("CORPUS_N", "40"))
    model = os.getenv("CORPUS_MODEL", "gpt-5.4-mini")
    out = os.getenv("CORPUS_OUT") or os.path.join(_ROOT, "data", "eval", "long_contracts_n40.json")
    if not (os.getenv("OPENAI_API_KEY") or "").strip():
        print("Missing OPENAI_API_KEY — aborting (no calls).")
        return
    print(f"Generating {n} DISTINCT contracts via openai:{model} → {out}")
    backend = make_backend("openai", model)
    contracts = await generate_long_contracts(backend, n=n, seed=1)
    save_long_contracts(contracts, out)
    got = load_long_contracts(out)
    toks = sum(len(c) for c in got) // 4
    print(f"Wrote {len(got)} contracts (~{toks} tok total, ~{toks // max(1, len(got))} tok/doc).")
    print(f"Distinct: {len(set(got))}/{len(got)} (want all-distinct).")
    print(f"Point the run at it:  SCALED_CONTRACTS={out} .venv/bin/python spikes/scaled_adaptive_run.py")


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\nAborted — no further calls.")
