"""
ERC-8004 client wrapper.

In MOCK_MODE, agent identities and reputation scores come from
agents/shared/mocks/erc8004_data.json. In real mode, calls go to the live
contracts on Sepolia.

Critical rule (per erc-8004-integration skill): NEVER generate ABI from memory.
The pinned ABI lives at contracts/erc8004-v1-abi.json.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import structlog
from eth_account import Account
from web3 import Web3

from .settings import get_settings

log = structlog.get_logger(__name__)

# Where the pinned artifacts live (mounted into containers)
ABI_PATH = Path(__file__).resolve().parent.parent.parent / "contracts" / "erc8004-v1-abi.json"
ADDRESSES_PATH = Path(__file__).resolve().parent.parent.parent / "contracts" / "deployed-addresses.json"
MOCK_DATA_PATH = Path(__file__).resolve().parent / "mocks" / "erc8004_data.json"


@dataclass
class AgentRecord:
    agent_id: int
    owner: str
    endpoint: str
    ens_name: str
    registered_at: int
    profile: Optional[str] = None    # v2: "swing" | "scalper" (None for legacy entries)


@dataclass
class ReputationStats:
    total_attestations: int
    wins: int
    losses: int
    score: int


class ERC8004Client:
    """Read + write client for ERC-8004 v1.0 (Sepolia)."""

    def __init__(self, signer_priv_key: Optional[str] = None):
        self.settings = get_settings()
        self._abis = json.loads(ABI_PATH.read_text())
        self._addresses = json.loads(ADDRESSES_PATH.read_text())["sepolia"]
        self._signer_priv_key = signer_priv_key
        self._mock = self.settings.MOCK_MODE

        # Always load mock data so fallback paths work even in real mode
        self._mock_data = json.loads(MOCK_DATA_PATH.read_text())

        if not self._mock:
            self._w3 = Web3(Web3.HTTPProvider(self.settings.SEPOLIA_RPC))
            self._identity = self._w3.eth.contract(
                address=self._addresses["ERC8004_IdentityRegistry"],
                abi=self._abis["IdentityRegistry"],
            )
            self._reputation = self._w3.eth.contract(
                address=self._addresses["ERC8004_ReputationRegistry"],
                abi=self._abis["ReputationRegistry"],
            )

    # ─────────────────────────────────────────────────────────────────
    # Identity
    # ─────────────────────────────────────────────────────────────────

    def get_agent(self, agent_id: int) -> AgentRecord:
        if self._mock:
            for a in self._mock_data["agents"]:
                if a["agent_id"] == agent_id:
                    return AgentRecord(**a)
            raise KeyError(f"agent {agent_id} not in mock data")

        try:
            result = self._identity.functions.getAgent(agent_id).call()
            return AgentRecord(
                agent_id=agent_id,
                owner=result[0],
                endpoint=result[1],
                ens_name=result[2],
                registered_at=result[3],
            )
        except Exception as exc:
            log.warning("erc8004_get_agent_fallback_to_mock", agent_id=agent_id, error=str(exc))
            for a in self._mock_data["agents"]:
                if a["agent_id"] == agent_id:
                    return AgentRecord(**a)
            raise KeyError(f"agent {agent_id} not in mock data or on-chain")

    def total_agents(self) -> int:
        if self._mock:
            return len(self._mock_data["agents"])
        try:
            return self._identity.functions.totalAgents().call()
        except Exception as exc:
            log.warning("erc8004_total_agents_fallback_to_mock", error=str(exc))
            return len(self._mock_data["agents"])

    def list_agents(self) -> list[AgentRecord]:
        if self._mock:
            return [AgentRecord(**a) for a in self._mock_data["agents"]]
        try:
            return [self.get_agent(i + 1) for i in range(self.total_agents())]
        except Exception as exc:
            log.warning("erc8004_list_agents_fallback_to_mock", error=str(exc))
            return [AgentRecord(**a) for a in self._mock_data["agents"]]

    # ─────────────────────────────────────────────────────────────────
    # Reputation
    # ─────────────────────────────────────────────────────────────────

    def get_reputation_score(self, agent_id: int) -> int:
        if self._mock:
            return self._mock_data["reputation_scores"].get(str(agent_id), 0)
        try:
            return self._reputation.functions.getReputationScore(agent_id).call()
        except Exception as exc:
            log.warning("erc8004_reputation_fallback_to_mock", agent_id=agent_id, error=str(exc))
            return self._mock_data["reputation_scores"].get(str(agent_id), 0)

    def get_stats(self, agent_id: int) -> ReputationStats:
        if self._mock:
            stats = self._mock_data["reputation_stats"].get(str(agent_id))
            if stats:
                return ReputationStats(**stats)
            return ReputationStats(total_attestations=0, wins=0, losses=0, score=0)
        try:
            result = self._reputation.functions.getStats(agent_id).call()
            return ReputationStats(
                total_attestations=result[0],
                wins=result[1],
                losses=result[2],
                score=result[3],
            )
        except Exception as exc:
            log.warning("erc8004_stats_fallback_to_mock", agent_id=agent_id, error=str(exc))
            stats = self._mock_data["reputation_stats"].get(str(agent_id))
            if stats:
                return ReputationStats(**stats)
            return ReputationStats(total_attestations=0, wins=0, losses=0, score=0)

    # ─────────────────────────────────────────────────────────────────
    # Attestation (Validator only)
    # ─────────────────────────────────────────────────────────────────

    def attest(
        self,
        agent_id: int,
        signal_id: bytes,
        win: bool,
        pnl_bps: int,
        weight: int,
    ) -> str:
        """
        Posts an attestation to ReputationRegistry.attest(...).
        Returns the transaction hash.

        Caller must have provided signer_priv_key in __init__ (Validator's key).
        """
        if not self._signer_priv_key:
            raise RuntimeError("attest() requires signer_priv_key at init")

        if self._mock:
            tx_hash = "0x" + signal_id.hex()[:60] + "ATSD"
            log.info(
                "erc8004_mock_attestation",
                agent_id=agent_id,
                signal_id="0x" + signal_id.hex(),
                win=win,
                pnl_bps=pnl_bps,
                weight=weight,
                tx_hash=tx_hash,
            )
            # Update mock score in-memory (would persist to a real chain)
            current = self._mock_data["reputation_scores"].get(str(agent_id), 0)
            delta = (1 if win else -1) * abs(pnl_bps) * weight // 10_000
            self._mock_data["reputation_scores"][str(agent_id)] = current + delta
            return tx_hash

        signer = Account.from_key(self._signer_priv_key)
        tx = self._reputation.functions.attest(
            agent_id, signal_id, win, pnl_bps, weight
        ).build_transaction({
            "from": signer.address,
            "nonce": self._w3.eth.get_transaction_count(signer.address),
            "gas": 200_000,
            "maxFeePerGas": self._w3.to_wei(50, "gwei"),
            "maxPriorityFeePerGas": self._w3.to_wei(2, "gwei"),
            "chainId": self.settings.CHAIN_ID_SEPOLIA,
        })
        signed = signer.sign_transaction(tx)
        tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
        log.info("erc8004_attestation_submitted", tx_hash=tx_hash.hex())
        return tx_hash.hex()
