'use client';

import Link from 'next/link';

import { AgentForm } from '@/components/AgentForm';
import { Web3Provider } from '@/components/Web3Provider';

export default function ForgePage() {
  return (
    <Web3Provider>
    <main className="forge-page">
      <header className="forge-bar">
        <Link href="/" className="forge-bar__brand" aria-label="SibylFi home">
          <svg width="28" height="28" viewBox="0 0 32 32" fill="none" aria-hidden>
            <circle cx="16" cy="16" r="14" stroke="#d4af37" strokeWidth="1" />
            <circle cx="16" cy="16" r="9"  stroke="#9b6dff" strokeWidth="0.8" opacity="0.7" />
            <path d="M 4 16 Q 16 8 28 16 Q 16 24 4 16 Z" stroke="#d4af37" strokeWidth="1" fill="none" />
            <circle cx="16" cy="16" r="3"   fill="#d4af37" />
            <circle cx="16" cy="16" r="1.2" fill="#0a0612" />
          </svg>
          <span className="forge-bar__name">Sibyl<em>Fi</em></span>
        </Link>
        <Link href="/" className="forge-bar__back">← Return to ledger</Link>
      </header>

      <section className="forge-intro">
        <div className="forge-eyebrow">⌬ THE FORGE</div>
        <h1 className="forge-title">Inscribe a new sibyl into the ledger.</h1>
        <p className="forge-lede">
          Pick a strategy profile and the orchestrator spins up a wallet-backed, signed-signal
          publisher — built on the same rule engine that powers
          {' '}<code>swing.sibylfi.eth</code> and <code>scalper.sibylfi.eth</code>.
          Once you publish, the validator settles your outcomes against Uniswap V3 TWAP
          and reputation accrues on ERC-8004.
        </p>
      </section>

      <div className="agent-form-shell">
        <AgentForm />
      </div>
    </main>
    </Web3Provider>
  );
}
