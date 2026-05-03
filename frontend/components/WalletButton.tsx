'use client';

import { useAccount, useConnect, useDisconnect, useChainId, useSwitchChain } from 'wagmi';
import { baseSepolia } from 'wagmi/chains';
import { useState } from 'react';

/**
 * Top-bar wallet button. Three states:
 *   disconnected → "Connect wallet" → opens injected provider
 *   wrong-chain  → "Switch to Base Sepolia" → wallet_switchEthereumChain
 *   connected    → "0xabcd…1234" → click again to disconnect
 *
 * Renders the same shell + sigil as the prototype's placeholder button so
 * the visual rhythm doesn't change when wallet state flips.
 */
export function WalletButton() {
  const { address, isConnected } = useAccount();
  const chainId = useChainId();
  const { connectors, connect, isPending: connecting } = useConnect();
  const { switchChain, isPending: switching } = useSwitchChain();
  const { disconnect } = useDisconnect();
  const [open, setOpen] = useState(false);

  const onClickRoot = () => {
    if (!isConnected) {
      const c = connectors[0];
      if (!c) {
        alert('No injected wallet detected. Install MetaMask or Rabby.');
        return;
      }
      connect({ connector: c });
      return;
    }
    if (chainId !== baseSepolia.id) {
      switchChain({ chainId: baseSepolia.id });
      return;
    }
    setOpen((v) => !v);
  };

  const state = !isConnected
    ? 'disconnected'
    : chainId !== baseSepolia.id
    ? 'wrong-chain'
    : 'connected';

  const label =
    state === 'disconnected' ? (connecting ? 'Opening wallet…' : 'Connect wallet')
    : state === 'wrong-chain' ? (switching ? 'Switching…' : 'Switch to Base Sepolia')
    : `${address!.slice(0, 6)}…${address!.slice(-4)}`;

  return (
    <div style={{ position: 'relative' }}>
      <button
        type="button"
        className="sf-wallet"
        data-state={state === 'connected' ? 'connected' : 'disconnected'}
        onClick={onClickRoot}
        disabled={connecting || switching}
      >
        <span className="sf-wallet-status" aria-hidden />
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" strokeWidth="1.2" aria-hidden>
          <rect x="1.5" y="3" width="11" height="8" rx="1" />
          <path d="M1.5 5.5h11" />
          <circle cx="9.5" cy="8" r="0.8" fill="currentColor" stroke="none" />
        </svg>
        <span>{label}</span>
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none" strokeWidth="1.2" aria-hidden style={{ marginLeft: 2, opacity: 0.7 }}>
          <path d="M3.5 2 L7 5 L3.5 8" />
        </svg>
      </button>
      {open && state === 'connected' && (
        <div
          style={{
            position: 'absolute', right: 0, top: 'calc(100% + 6px)',
            background: 'var(--sf-bg-panel, #0d0c12)', border: '1px solid var(--sf-border, #2a2640)',
            padding: 10, minWidth: 200, zIndex: 50,
            fontFamily: 'JetBrains Mono, monospace', fontSize: 11,
          }}
        >
          <div style={{ color: 'var(--sf-fg-dim)', marginBottom: 8, letterSpacing: '0.1em' }}>SESSION</div>
          <div style={{ color: 'var(--sf-fg)', wordBreak: 'break-all', marginBottom: 10 }}>{address}</div>
          <button
            type="button"
            className="sf-btn sf-btn-sm sf-btn-ghost"
            onClick={() => { disconnect(); setOpen(false); }}
            style={{ width: '100%' }}
          >
            Disconnect
          </button>
        </div>
      )}
    </div>
  );
}
