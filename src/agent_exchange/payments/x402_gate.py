"""x402 ``upto``-scheme verify/settle gate for the Agent Exchange.

This module is the load-bearing money seam. It wraps the x402 ``upto`` payment
scheme (Permit2-based) plus the HTTP facilitator so the platform can:

1. **VERIFY** a buyer's payment authorization up front — no money moves. The buyer
   programmatically signs a Permit2 ``PermitWitnessTransferFrom`` authorizing the
   facilitator to pull *up to* a maximum amount of USDC to a given payout wallet.
2. **SETTLE** a chosen amount *less than or equal to* that authorized maximum —
   money moves on-chain. This per-payment prorate (settle < authorized) is exactly
   what the ``upto`` scheme exists for; the ``exact`` scheme (EIP-3009) cannot do it.

Why ``upto`` and not ``exact``
------------------------------
With ``exact`` the signed amount and the settled amount are identical (EIP-3009
``transferWithAuthorization``). For pay-on-grade prorating we need the buyer to
authorize a ceiling once, then have the platform settle a smaller, work-dependent
figure. The ``upto`` scheme signs a Permit2 witness carrying the *maximum*
(``permitted.amount``) and lets the facilitator transfer any amount ``<=`` that
maximum, named at settle time.

How the settle amount is specified (verified against the installed library)
---------------------------------------------------------------------------
The facilitator's settle entrypoint
(``x402.mechanisms.evm.upto.permit2_utils.settle_upto_permit2``) takes the
settlement amount from ``requirements.amount`` on the *settle* call — NOT from the
signed payload. The signed payload's ``permit2_authorization.permitted.amount`` is
the authorized **maximum**; settle re-verifies the signature against that maximum,
then guards ``settlement_amount <= permitted_amount`` (else
``ERR_UPTO_SETTLEMENT_EXCEEDS_AMOUNT``) before calling the on-chain proxy's
``settle(permit, amount, owner, witness, sig)`` with ``amount = requirements.amount``.

Therefore: ``authorize`` signs a requirement whose ``amount`` is the MAX, and
``settle`` is handed a requirement whose ``amount`` is the ACTUAL (<= max). This
gate builds those two requirements from the same base config.

Permit2 prerequisite
--------------------
``upto`` settles by having the Permit2 contract (canonical
``0x000000000022D473030F116dDEE9F6B43aC78BA3``) pull the buyer's USDC. That
requires a one-time on-chain ERC-20 ``approve(Permit2, amount)`` from the buyer's
wallet — the offline Permit2 witness signature alone is not enough; Permit2 itself
must hold an allowance. :meth:`X402Gate.ensure_permit2_approval` performs that
approval idempotently (checks current allowance first, sends a tx only if short).

All addresses/amounts are USDC atomic units (6 decimals) on Base Sepolia
(``eip155:84532``) by default.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from x402.mechanisms.evm.constants import (
    ERC20_ALLOWANCE_ABI,
    ERC20_APPROVE_ABI,
    PERMIT2_ADDRESS,
)
from x402.mechanisms.evm.upto import UptoEvmClientScheme
from x402.mechanisms.evm.utils import get_evm_chain_id
from x402.schemas import PaymentPayload, PaymentRequirements

logger = logging.getLogger("agent_exchange.payments.x402_gate")

# A sane default Permit2 allowance: the max uint256, so a single approval covers
# every future settle. (USDC tolerates an unbounded Permit2 allowance — this is the
# standard Permit2 onboarding pattern.)
_MAX_UINT256 = (1 << 256) - 1

# Public Base Sepolia JSON-RPC endpoint, used only for the one-time Permit2 approval
# (the verify/settle path goes through the HTTP facilitator, not this RPC).
_DEFAULT_BASE_SEPOLIA_RPC = "https://sepolia.base.org"

# A generous default authorization window. The buyer signs at hire time; settlement
# happens after the work is graded, which can be many minutes later.
_DEFAULT_MAX_TIMEOUT_SECONDS = 3600


class _Facilitator(Protocol):
    """The slice of ``HTTPFacilitatorClient`` this gate depends on.

    ``verify`` / ``settle`` are async; ``get_supported`` is sync (the x402 client
    calls it during initialization, so it is deliberately not a coroutine).
    """

    async def verify(self, payload: Any, requirements: Any) -> Any: ...
    async def settle(self, payload: Any, requirements: Any) -> Any: ...
    def get_supported(self) -> Any: ...


class _EvmSigner(Protocol):
    """The slice of an x402 EVM client signer this gate depends on."""

    address: str

    def sign_typed_data(self, *args: Any, **kwargs: Any) -> bytes: ...


class X402Gate:
    """``upto``-scheme payment gate: authorize→verify up front, settle (<=max) later.

    Implements the ``PaymentGate`` Protocol in ``agent_exchange.payments.types``.
    ``requirement`` objects are :class:`x402.schemas.PaymentRequirements`; ``payload``
    objects are :class:`x402.schemas.PaymentPayload` — both opaque to callers above
    this seam.

    The gate holds the buyer's EVM signer, an HTTP facilitator client, and the
    network/asset config. The facilitator's signer address (needed in every
    requirement's ``extra.facilitatorAddress`` so the Permit2 witness binds to the
    facilitator that will settle) is fetched once from ``get_supported()`` and cached.
    """

    def __init__(
        self,
        buyer_signer: _EvmSigner,
        facilitator: _Facilitator,
        *,
        network: str,
        asset_address: str,
        max_timeout_seconds: int = _DEFAULT_MAX_TIMEOUT_SECONDS,
        rpc_url: str = _DEFAULT_BASE_SEPOLIA_RPC,
    ) -> None:
        """
        Args:
            buyer_signer: The buyer's x402 EVM client signer (e.g.
                ``EthAccountSigner(Account.from_key(...))``). Used to sign the upto
                Permit2 authorization and, for the Permit2 approval, to send the
                on-chain ``approve`` tx via its underlying ``eth_account`` account.
            facilitator: An ``HTTPFacilitatorClient`` pointed at a facilitator that
                supports ``upto`` on ``network``.
            network: CAIP-2 network id, e.g. ``"eip155:84532"`` (Base Sepolia).
            asset_address: The USDC token address on ``network`` (6 decimals).
            max_timeout_seconds: Authorization validity window (seconds).
            rpc_url: JSON-RPC endpoint for the one-time Permit2 ``approve`` only.
        """
        self._buyer_signer = buyer_signer
        self._facilitator = facilitator
        self._network = network
        self._asset = asset_address
        self._max_timeout_seconds = max_timeout_seconds
        self._rpc_url = rpc_url
        self._client_scheme = UptoEvmClientScheme(buyer_signer)
        # Lazily resolved + cached facilitator signer address for this network.
        self._facilitator_address: str | None = None

    # -- requirement construction ------------------------------------------------

    def _resolve_facilitator_address(self) -> str:
        """Fetch + cache the facilitator's signer address for ``upto`` on this network.

        The upto client signs a witness binding the authorization to a specific
        facilitator address; the facilitator advertises it under the matching
        ``upto`` kind's ``extra.facilitatorAddress`` in ``get_supported()`` (with a
        fallback to the ``signers`` map keyed by ``eip155:*``). Raises if the
        facilitator does not support ``upto`` on this network.
        """
        if self._facilitator_address is not None:
            return self._facilitator_address

        supported = self._facilitator.get_supported()

        # Preferred source: the upto kind's extra.facilitatorAddress for this network.
        for kind in getattr(supported, "kinds", []) or []:
            if getattr(kind, "scheme", None) != "upto":
                continue
            if str(getattr(kind, "network", "")) != self._network:
                continue
            extra = getattr(kind, "extra", None) or {}
            addr = extra.get("facilitatorAddress")
            if addr:
                self._facilitator_address = addr
                return addr

        # Fallback: the signers map (keyed by CAIP family, e.g. "eip155:*").
        signers = getattr(supported, "signers", None) or {}
        family = self._network.split(":", 1)[0] + ":*"
        candidates = signers.get(family) or signers.get(self._network) or []
        if candidates:
            self._facilitator_address = candidates[0]
            return candidates[0]

        raise RuntimeError(
            f"facilitator does not advertise an 'upto' signer for network "
            f"{self._network!r}; cannot build an upto requirement"
        )

    def build_requirement(self, *, amount_atomic: int, pay_to: str) -> PaymentRequirements:
        """Build an ``upto`` payment requirement for ``amount_atomic`` → ``pay_to``.

        ``amount_atomic`` is the worker's MAXIMUM (atomic USDC, 6 decimals) — the
        ceiling the buyer authorizes. ``PaymentRequirements.amount`` is a string on
        the wire, so the atomic int is stringified. The required
        ``extra.facilitatorAddress`` is resolved from the facilitator.
        """
        if amount_atomic < 0:
            raise ValueError("amount_atomic must be non-negative")
        return PaymentRequirements(
            scheme="upto",
            network=self._network,
            asset=self._asset,
            amount=str(amount_atomic),
            pay_to=pay_to,
            max_timeout_seconds=self._max_timeout_seconds,
            extra={"facilitatorAddress": self._resolve_facilitator_address()},
        )

    # -- authorize / verify / settle ---------------------------------------------

    async def authorize(self, requirement: PaymentRequirements) -> PaymentPayload:
        """Buyer programmatically signs an upto authorization for ``requirement``'s max.

        Produces the signed Permit2 ``PermitWitnessTransferFrom`` payload (no HTTP-402
        round trip) and wraps it as a :class:`PaymentPayload` the facilitator's
        ``verify``/``settle`` accept. The signed ``permitted.amount`` equals
        ``requirement.amount`` — i.e. the authorized maximum.
        """
        payload_dict = self._client_scheme.create_payment_payload(requirement)
        return PaymentPayload(
            x402_version=2,
            payload=payload_dict,
            accepted=requirement,
        )

    async def verify(self, payload: PaymentPayload, requirement: PaymentRequirements) -> bool:
        """Validate the authorization with the facilitator WITHOUT moving money.

        Returns ``True`` iff the facilitator reports the authorization valid (good
        signature, recipient/facilitator/amount/token match, deadline live, allowance
        + balance sufficient). Network/facilitator errors are logged and treated as
        ``False`` — a failed verify must never read as authorized.
        """
        try:
            response = await self._facilitator.verify(payload, requirement)
        except Exception as exc:  # noqa: BLE001 - any failure ⇒ not verified
            logger.warning("x402 upto verify failed: %s", exc)
            return False

        is_valid = bool(getattr(response, "is_valid", False))
        if not is_valid:
            logger.warning(
                "x402 upto verify rejected: reason=%s message=%s",
                getattr(response, "invalid_reason", None),
                getattr(response, "invalid_message", None),
            )
        return is_valid

    async def settle(
        self,
        payload: PaymentPayload,
        requirement: PaymentRequirements,
        *,
        amount_atomic: int,
    ) -> str:
        """Settle ``amount_atomic`` (<= the authorized max) on-chain; return the tx hash.

        The settle amount is specified by handing the facilitator a requirement whose
        ``amount`` is the ACTUAL figure to move (not the signed maximum). The
        facilitator re-verifies the signature against the payload's
        ``permitted.amount`` (the max), guards ``amount_atomic <= max``, then transfers
        ``amount_atomic`` via the upto Permit2 proxy.

        A zero settlement is legal (the facilitator returns success with an empty
        ``transaction`` and no on-chain tx) — useful when grading withholds all pay.

        Raises:
            ValueError: if ``amount_atomic`` exceeds the authorized maximum.
            RuntimeError: if the facilitator reports settlement failure.
        """
        if amount_atomic < 0:
            raise ValueError("amount_atomic must be non-negative")

        authorized_max = int(requirement.amount)
        if amount_atomic > authorized_max:
            raise ValueError(
                f"settle amount {amount_atomic} exceeds authorized maximum "
                f"{authorized_max}"
            )

        # Same requirement, but amount = the ACTUAL figure to move. Everything else
        # (scheme/network/asset/pay_to/extra) must match what was signed/verified.
        settle_requirement = PaymentRequirements(
            scheme=requirement.scheme,
            network=requirement.network,
            asset=requirement.asset,
            amount=str(amount_atomic),
            pay_to=requirement.pay_to,
            max_timeout_seconds=requirement.max_timeout_seconds,
            extra=requirement.extra,
        )

        response = await self._facilitator.settle(payload, settle_requirement)

        if not bool(getattr(response, "success", False)):
            reason = getattr(response, "error_reason", None)
            message = getattr(response, "error_message", None)
            logger.warning("x402 upto settle failed: reason=%s message=%s", reason, message)
            raise RuntimeError(
                f"x402 upto settle failed: reason={reason} message={message}"
            )

        return getattr(response, "transaction", "") or ""

    # -- one-time Permit2 approval ----------------------------------------------

    async def ensure_permit2_approval(self) -> str | None:
        """Ensure the buyer has approved the Permit2 contract to spend its USDC.

        ``upto`` settles via Permit2 pulling the buyer's USDC, which requires a
        standard on-chain ERC-20 ``approve(Permit2, allowance)`` from the buyer once
        per (wallet, token). This reads the current allowance and only sends a tx if
        it is short, so it is idempotent and safe to call before every job.

        Returns:
            The approval transaction hash if one was sent, or ``None`` if the existing
            allowance already covers settlement (no tx needed).

        Raises:
            RuntimeError: if the underlying signer does not expose an ``eth_account``
                account (this gate cannot sign+send the approve tx without it).
        """
        from web3 import Web3

        account = self._extract_local_account()
        if account is None:
            raise RuntimeError(
                "ensure_permit2_approval requires a buyer signer backed by an "
                "eth_account LocalAccount (e.g. EthAccountSigner); none found"
            )

        w3 = Web3(Web3.HTTPProvider(self._rpc_url))
        owner = Web3.to_checksum_address(self._buyer_signer.address)
        token = Web3.to_checksum_address(self._asset)
        permit2 = Web3.to_checksum_address(PERMIT2_ADDRESS)

        allowance_contract = w3.eth.contract(address=token, abi=ERC20_ALLOWANCE_ABI)
        current = int(allowance_contract.functions.allowance(owner, permit2).call())
        if current >= _MAX_UINT256 // 2:
            # Already an effectively-unbounded allowance — nothing to do.
            logger.info("Permit2 already approved for %s (allowance=%s)", token, current)
            return None

        approve_contract = w3.eth.contract(address=token, abi=ERC20_APPROVE_ABI)
        chain_id = get_evm_chain_id(self._network)
        nonce = w3.eth.get_transaction_count(owner)
        tx = approve_contract.functions.approve(permit2, _MAX_UINT256).build_transaction(
            {
                "from": owner,
                "nonce": nonce,
                "chainId": chain_id,
            }
        )
        signed = account.sign_transaction(tx)
        raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
        tx_hash = w3.eth.send_raw_transaction(raw)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        tx_hex = tx_hash.hex()
        if not tx_hex.startswith("0x"):
            tx_hex = "0x" + tx_hex
        if receipt.status != 1:
            raise RuntimeError(f"Permit2 approve tx reverted: {tx_hex}")
        logger.info("Permit2 approved for %s in tx %s", token, tx_hex)
        return tx_hex

    def _extract_local_account(self) -> Any | None:
        """Best-effort unwrap of the underlying ``eth_account`` LocalAccount.

        ``EthAccountSigner`` stores it on ``_account``; a raw LocalAccount may have
        been passed directly. Returns ``None`` if neither shape matches.
        """
        inner = getattr(self._buyer_signer, "_account", None)
        if inner is not None and hasattr(inner, "sign_transaction"):
            return inner
        if hasattr(self._buyer_signer, "sign_transaction"):
            return self._buyer_signer
        return None


def make_x402_gate(
    buyer_private_key: str,
    *,
    facilitator_url: str,
    network: str,
    asset_address: str,
    max_timeout_seconds: int = _DEFAULT_MAX_TIMEOUT_SECONDS,
    rpc_url: str = _DEFAULT_BASE_SEPOLIA_RPC,
) -> X402Gate:
    """Wire an :class:`X402Gate` from a buyer private key + facilitator URL.

    Builds an ``eth_account`` from ``buyer_private_key``, wraps it in the x402
    ``EthAccountSigner``, and points an ``HTTPFacilitatorClient`` at
    ``facilitator_url``.

    Args:
        buyer_private_key: The buyer wallet's EVM private key (hex, ``0x``-prefixed
            or not). This wallet signs authorizations and the Permit2 approval, and
            its USDC is what moves on settle.
        facilitator_url: e.g. ``"https://x402.org/facilitator"``.
        network: CAIP-2 network id, e.g. ``"eip155:84532"``.
        asset_address: USDC token address on ``network`` (6 decimals).
        max_timeout_seconds: Authorization validity window (seconds).
        rpc_url: JSON-RPC endpoint for the one-time Permit2 approval only.
    """
    from eth_account import Account

    from x402.http import FacilitatorConfig, HTTPFacilitatorClient
    from x402.mechanisms.evm import EthAccountSigner

    account = Account.from_key(buyer_private_key)
    signer = EthAccountSigner(account)
    facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=facilitator_url))
    return X402Gate(
        signer,
        facilitator,
        network=network,
        asset_address=asset_address,
        max_timeout_seconds=max_timeout_seconds,
        rpc_url=rpc_url,
    )
