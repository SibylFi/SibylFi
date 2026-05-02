"""
Signing helpers for SibylFi.

All Research Agents sign signals using their wallet keys. Trading and Risk
Agents verify signatures before trusting payloads.

Signature scheme: keccak256(canonical_json) signed with eth_account.
Canonical JSON: signature field excluded, keys sorted alphabetically, no whitespace.
"""
from __future__ import annotations

from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

from .signal_schema import RiskAttestation, Signal


def sign_signal(signal: Signal, priv_key: str) -> str:
    """
    Sign a Signal. Returns hex signature; caller assigns to signal.signature
    AFTER signing the canonical bytes (which exclude `signature`).

    Idiomatic usage:
        sig = Signal(..., signature="0x")  # placeholder
        sig.signature = sign_signal(sig, priv_key)
    """
    canonical = signal.canonicalize()
    digest = Web3.keccak(canonical)
    msg = encode_defunct(digest)
    signed = Account.sign_message(msg, private_key=priv_key)
    return signed.signature.hex()


def verify_signal(signal: Signal, expected_signer: str) -> bool:
    """
    Verify the signature against an expected signer address (the publisher's
    wallet).
    """
    canonical = signal.canonicalize()
    digest = Web3.keccak(canonical)
    msg = encode_defunct(digest)
    try:
        recovered = Account.recover_message(msg, signature=signal.signature)
    except Exception:
        return False
    return recovered.lower() == expected_signer.lower()


def sign_risk_attestation(attestation: RiskAttestation, priv_key: str) -> str:
    """Sign a RiskAttestation similarly (excluded signature field, sorted keys)."""
    body = attestation.model_dump(by_alias=True, exclude={"signature"})
    import json
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    digest = Web3.keccak(canonical)
    msg = encode_defunct(digest)
    signed = Account.sign_message(msg, private_key=priv_key)
    return signed.signature.hex()
