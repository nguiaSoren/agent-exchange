"""Check the BUYER wallet's test-USDC balance on Base Sepolia.

Run this after funding at faucet.circle.com to know when the coin has landed
(read-only RPC call — no server, no signing, no risk):

    .venv/bin/python spikes/check_balance.py
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from eth_account import Account
from web3 import Web3

load_dotenv()

RPC = os.getenv("BASE_SEPOLIA_RPC", "https://sepolia.base.org")
USDC = os.getenv("X402_USDC_ADDRESS", "0x036CbD53842c5426634e7929541eC2318f3dCF7e")
ERC20_BALANCEOF = [
    {
        "constant": True,
        "inputs": [{"name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    }
]

addr = Account.from_key(os.environ["EVM_PRIVATE_KEY"]).address
w3 = Web3(Web3.HTTPProvider(RPC))
usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC), abi=ERC20_BALANCEOF)
atomic = usdc.functions.balanceOf(Web3.to_checksum_address(addr)).call()
usdc_balance = atomic / 1e6

print(f"buyer {addr}")
print(f"  test-USDC on Base Sepolia: {usdc_balance:.6f}  ({atomic} atomic)")
if atomic >= 1000:  # need $0.001 = 1000 atomic for the spike
    print("  ✅ funded — run:  .venv/bin/python spikes/x402_buyer.py")
else:
    print("  ⏳ not landed yet — wait ~30s and re-run this check")
