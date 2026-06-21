"""Pilot pre-flight (L3/L6): one live call to every model in the spine so nothing 404s mid-run,
plus a prompt-caching proof on a real contract (reads usage.prompt_tokens_details.cached_tokens,
which the backend does not surface). Tiny spend (~$0.05). Run before the n=4 pilot.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import httpx
from dotenv import load_dotenv

from agent_exchange.core import make_backend
from agent_exchange.core.types import Message

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"))

PINGS = [
    ("openai", "gpt-5.4-nano"), ("openai", "gpt-5.4"), ("openai", "gpt-5.5-2026-04-23"),
    ("openrouter", "anthropic/claude-opus-4.8"), ("openrouter", "anthropic/claude-sonnet-4.6"),
    ("openrouter", "deepseek/deepseek-v3.2"),
]


async def _ping(p: str, m: str) -> str:
    try:
        b = make_backend(p, m)
        r = await b.complete([Message.user("Reply with the single word OK.")], max_tokens=16)
        return f"  OK    {p}:{m:34} in={r.usage.input_tokens} out={r.usage.output_tokens} finish={r.finish_reason}"
    except Exception as e:  # noqa: BLE001
        return f"  FAIL  {p}:{m:34} {type(e).__name__}: {str(e)[:110]}"


async def _cache_check() -> str:
    key = os.environ["OPENAI_API_KEY"].strip()
    contract = json.load(open(os.path.join(_ROOT, "data/eval/long_contracts_real.json")))["contracts"][0]
    body = {
        "model": "gpt-5.4-nano",
        "messages": [
            {"role": "system", "content": "You are a contract verifier. Answer in one word."},
            {"role": "user", "content": f"CONTRACT:\n\"\"\"\n{contract}\n\"\"\"\n\nIs this a contract? yes/no."},
        ],
        "max_completion_tokens": 16,
    }
    lines = []
    async with httpx.AsyncClient(timeout=60) as c:
        for i in range(3):
            r = await c.post("https://api.openai.com/v1/chat/completions", json=body,
                             headers={"Authorization": f"Bearer {key}"})
            u = r.json().get("usage", {})
            cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
            lines.append(f"  call {i + 1}: prompt_tokens={u.get('prompt_tokens')}  cached_tokens={cached}")
    return "\n".join(lines)


async def main() -> None:
    print("PING every spine/oracle/attacker model (live ID check):")
    print("\n".join(await asyncio.gather(*[_ping(p, m) for p, m in PINGS])))
    print("\nPROMPT-CACHING proof — same ~1.5k-token contract prefix x3 (gpt-5.4-nano):")
    print(await _cache_check())
    print("\n(cached_tokens > 0 on calls 2-3 => caching engaged.)")


if __name__ == "__main__":
    asyncio.run(main())
