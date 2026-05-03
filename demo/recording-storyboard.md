# Demo Recording Storyboard — SibylFi

> **Target:** 2:30 to 2:55 final cut. 1080p. Real human narration.
> **Audience:** ETHGlobal Open Agents judges.

## Constraints (per `hackathon-compliance` skill)

- ≥ 720p; we record at 1080p
- 2:00–4:00 length window; we target 2:30–2:55
- No AI voiceover — real human narration only
- No mobile recording
- No music-with-text-only segments

## Scene-by-scene

### Scene 1 — Opening (0:00–0:20)

**Visual:** Architecture diagram. Sponsor stack: 0G + ENS + Uniswap.
**Narration:**
> "SibylFi is a marketplace where AI trading agents publish, validate, and consume signals on-chain. Research agents publish prophecies. The Validator settles them against Uniswap TWAP. Reputation is reckoned, in the open. Built on 0G Compute, ENS, and Uniswap."

**OBS scene:** `01_overview` — static diagram + sponsor logos.

### Scene 2 — Agent identity (0:20–0:45)

**Visual:** SibylFi leaderboard. Three Research Agents already registered with subnames under sibylfi.eth.
**Action:** Click `reversal.sibylfi.eth` → opens agent profile. Show ENSIP-25 verification: ENS name → ERC-8004 entry, and back.
**Narration:**
> "Each agent has an ENS subname under sibylfi.eth, minted via Durin on Base Sepolia. Bidirectional ENSIP-25 verification ties the name to its ERC-8004 registry entry, both ways. This is the trust foundation — agents can't impersonate each other, and reputation can't be forged."

**OBS scene:** `02_profile_zoom` — close-up on agent profile, zoom into ENSIP-25 panel.

### Scene 3 — Live signal flow (0:45–1:45)

**Visual:** Switch to "Rite of Divination" view. Click "Begin the rite".
**Action:** Walk through six stations, advancing each on cue:
1. Discover (ERC-8004 IdentityRegistry read)
2. x402 payment
3. Signal received (signed JSON)
4. Risk verification
5. Uniswap swap
6. (next scene)

**Narration:**
> "The Trading Agent discovers Research Agents via ERC-8004 — ranks them by reputation, picks the top one. It pays via x402 — actual USDC on Base Sepolia. The signal arrives, signed. The Risk Agent verifies it — also paid, deterministic checks. If risk passes, the swap goes through Uniswap's Trading API. All the agent-to-agent communication you just saw is the swarm pattern that 0G Track B is asking for."

**OBS scene:** `03_rite` — full flow view; click "Advance" on cue.

### Scene 4 — Settlement & reputation (1:45–2:30)

**Visual:** Wait briefly, then trigger validator settlement (or use demo control button).
**Action:** Settle a pre-staged signal. Show the leaderboard reordering live as reputation updates. Highlight the on-chain attestation receipt.
**Narration:**
> "Now the horizon expires. The Validator reads the 5-minute Uniswap V3 TWAP, computes PnL — gas-adjusted, with slippage attribution — and posts the attestation to ERC-8004. Watch the leaderboard. The reputation update happens in real time. This — right here — is the deterministic on-chain validation oracle. No human grader, no retroactive edits."

**OBS scene:** `04_settle_hero` — leaderboard at full screen; settlement triggers reorder + sonar pulse.

### Scene 5 — Close (2:30–2:55)

**Visual:** Closing slide with team, repo URL, "What we'd build next."
**Narration:**
> "Built by [team]. The repo, the demo, and our feedback for the Uniswap team are all linked. Thank you."

**OBS scene:** `05_outro` — static title card.

## Pre-recording checklist (run `bash scripts/check-health.sh` first)

- [ ] All services healthy
- [ ] Wallets funded with > 0.05 OG and > 0.05 Base Sepolia ETH
- [ ] At least one signal pre-published and pending settlement
- [ ] Browser cache cleared, F11 fullscreen mode
- [ ] OBS scenes pre-built and tested
- [ ] No browser dev tools visible
- [ ] Recording from a desktop, NOT a phone
- [ ] Microphone test: real human narration audible at -12 dBFS RMS

## Failure modes & contingencies

| If… | Then… |
|---|---|
| 0G Galileo is offline | Set `USE_FALLBACK_INFERENCE=1` and re-record. Note in README. |
| Coinbase facilitator returns errors | Set `MOCK_MODE=1` for demo recording. Trade-off: judges may notice. |
| Validator misses a horizon | Use orchestrator's `/demo/settle-now` button (mapped to a key in OBS). |
| Frontend animation stutters | Restart browser; close other tabs. |
| OBS drops frames | Reduce capture resolution to 1080p (already there); increase encoder bitrate. |

## Recording schedule

Record at minimum 6 hours before submission deadline so there's time for re-takes and editing. Don't record on the final day.
