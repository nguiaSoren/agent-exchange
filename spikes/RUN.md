# Spikes — run guide

Box 3 = x402 coin-move (below). Box 4 = Band room (`band_room.py`, at the bottom).

---

## x402 coin-move spike (box 3)

Everything is pre-wired. Throwaway **testnet** wallets are already in `.env` (no real money, ever). The venv has x402 installed and the imports are verified.

## Step 1 — fund the BUYER wallet (free, ~2 min)
Derive your buyer address from `EVM_PRIVATE_KEY` in `.env` (any throwaway testnet key). Go to **https://faucet.circle.com**, choose **Base Sepolia**, and paste *your* address.

It drops free **test USDC** into it. (You don't need test ETH — x402's `exact` scheme is gasless for the buyer; the facilitator pays gas.)

## Step 2 — run the seller (terminal A)
```bash
cd "agent-exchange"
.venv/bin/python spikes/x402_seller.py
# leave it running — serves GET /audit @ $0.001 on Base Sepolia
```

## Step 3 — run the buyer (terminal B)
```bash
cd "agent-exchange"
.venv/bin/python spikes/x402_buyer.py
```
Expected: `HTTP 200` + `✅ PAYMENT SETTLED` with an on-chain tx, and an explorer link
(`https://sepolia.basescan.org/tx/<hash>`). **That's the coin moving — box 3 DONE.**

If you see "Not settled / no test USDC": the faucet hasn't landed yet — wait a moment and re-run the buyer.

## Notes
- Wallets are **disposable, testnet-only**. Never put real funds in them.
- Re-install deps anytime: `uv pip install --python .venv "x402[fastapi]" "x402[httpx]" "x402[evm]" uvicorn python-dotenv`
  (the `[evm]` extra is required for the web3 signer — the official docs omit it).

---

## Band room spike (box 4) — `band_room.py`

Proves Band's room + @mention-routing + shared-context primitives on the real Agent API.

### Step 1 — sign up + create TWO agents (free, ~5 min, no hackathon code)
1. Go to **app.band.ai**, sign up, verify email.
2. Create **two agents** under your account (e.g. "Auditor-A" and "Auditor-B"). Each gives an **API key shown once** — copy both.
   - Note: Band agents need an LLM provider key set on your account (OpenAI/Anthropic/etc.) — you already have one.

### Step 2 — put the keys in `.env` (comments on their OWN lines!)
```
BAND_AGENT_A_KEY=<agent A key>
BAND_AGENT_B_KEY=<agent B key>
```
⚠️ Keep any comment on a separate line — `python-dotenv` reads an inline comment on a blank key as the value (caught during the dry-run).

### Step 3 — run it
```bash
cd "agent-exchange" && .venv/bin/python spikes/band_room.py
```
Expected: A creates a room, adds B, posts an `@`-mention; **B receives it via `/messages/next`** and reads it back from `/context`. That's a real message routed A→B through a real Band room — **box 4 DONE.**
