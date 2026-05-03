'use client';

import { useEffect, useMemo, useState } from 'react';
import { useAccount, useConnect, useDisconnect, useEnsAddress, useSignMessage } from 'wagmi';
import { sepolia } from 'wagmi/chains';

export interface OwnershipProof {
  address: `0x${string}`;
  message: string;
  signature: `0x${string}`;
  ens_resolves_to: `0x${string}` | null;
}

interface Props {
  ensName: string;            // e.g. "myslug.sibylfi.eth"
  onProof: (proof: OwnershipProof | null) => void;
}

type Stage =
  | { kind: 'idle' }
  | { kind: 'checking' }
  | { kind: 'unowned'; address: `0x${string}` }       // ENS doesn't resolve — claim path
  | { kind: 'owned';   address: `0x${string}`; resolved: `0x${string}` }
  | { kind: 'mismatch'; address: `0x${string}`; resolved: `0x${string}` }
  | { kind: 'signing' }
  | { kind: 'verified'; proof: OwnershipProof }
  | { kind: 'error'; message: string };

/**
 * Two-step ENS ownership gate:
 *   1. Connect wallet (injected provider).
 *   2. Resolve <ensName> on Sepolia. Three outcomes:
 *      - unresolved → unclaimed slug, anyone can claim with a wallet signature
 *      - resolved + matches connected wallet → owner, allow claim
 *      - resolved + mismatched → block; not the owner
 *   3. Sign a claim message → returns OwnershipProof to the parent form.
 *
 * The proof is cosmetic for now (orchestrator stores it but doesn't enforce
 * registry ownership yet — see contracts/SibylFiRegistrar). It demonstrates
 * the wallet-binding the production flow will eventually verify on-chain.
 */
export function EnsOwnershipGate({ ensName, onProof }: Props) {
  const { address, isConnected } = useAccount();
  const { connectors, connect, isPending: connecting } = useConnect();
  const { disconnect } = useDisconnect();
  const { signMessageAsync } = useSignMessage();

  const { data: resolvedAddr, isLoading: resolvingEns } = useEnsAddress({
    name: ensName,
    chainId: sepolia.id,
    query: { enabled: ensName.length > 8 && !!address },
  });

  const [stage, setStage] = useState<Stage>({ kind: 'idle' });

  // Reset proof when slug changes
  useEffect(() => {
    if (stage.kind === 'verified') {
      setStage({ kind: 'idle' });
      onProof(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ensName]);

  // Compute resolution stage when ENS data lands
  useEffect(() => {
    if (!isConnected || !address) return;
    if (resolvingEns) {
      setStage({ kind: 'checking' });
      return;
    }
    if (!resolvedAddr) {
      setStage({ kind: 'unowned', address });
      return;
    }
    if (resolvedAddr.toLowerCase() === address.toLowerCase()) {
      setStage({ kind: 'owned', address, resolved: resolvedAddr });
    } else {
      setStage({ kind: 'mismatch', address, resolved: resolvedAddr });
    }
  }, [isConnected, address, resolvedAddr, resolvingEns]);

  const message = useMemo(() => {
    const nonce = Math.random().toString(36).slice(2, 10);
    return [
      'SibylFi · Agent ownership claim',
      `ens:    ${ensName}`,
      `nonce:  ${nonce}`,
      `chain:  sepolia`,
    ].join('\n');
  }, [ensName, stage.kind === 'unowned' || stage.kind === 'owned']);

  const onConnect = () => {
    const c = connectors[0];
    if (!c) {
      setStage({ kind: 'error', message: 'No injected wallet detected. Install MetaMask or Rabby.' });
      return;
    }
    connect({ connector: c });
  };

  const onSign = async () => {
    if (stage.kind !== 'unowned' && stage.kind !== 'owned') return;
    setStage({ kind: 'signing' });
    try {
      const signature = await signMessageAsync({ message });
      const proof: OwnershipProof = {
        address: stage.address,
        message,
        signature,
        ens_resolves_to: stage.kind === 'owned' ? stage.resolved : null,
      };
      setStage({ kind: 'verified', proof });
      onProof(proof);
    } catch (e) {
      setStage({ kind: 'error', message: e instanceof Error ? e.message : 'Signature rejected' });
    }
  };

  // ── Render ──
  if (!isConnected) {
    return (
      <div className="ens-gate ens-gate--idle">
        <div className="ens-gate__title">ENS ownership · not verified</div>
        <p className="ens-gate__sub">
          Connect a wallet to claim <code>{ensName}</code>. We&apos;ll resolve the name
          on Sepolia and ask you to sign a one-line claim — no transaction, no gas.
        </p>
        <button type="button" className="ens-gate__btn" onClick={onConnect} disabled={connecting}>
          {connecting ? 'Opening wallet…' : 'Connect wallet'}
        </button>
      </div>
    );
  }

  if (stage.kind === 'verified') {
    return (
      <div className="ens-gate ens-gate--ok">
        <div className="ens-gate__title">✓ Ownership signed</div>
        <p className="ens-gate__sub">
          <code>{stage.proof.address.slice(0, 8)}…{stage.proof.address.slice(-4)}</code>
          {' '}signed a claim for <code>{ensName}</code>.
          {stage.proof.ens_resolves_to
            ? ' ENS already resolves to this wallet.'
            : ' ENS is unresolved on Sepolia — slug is yours to claim.'}
        </p>
        <button type="button" className="ens-gate__btn ens-gate__btn--secondary"
                onClick={() => { onProof(null); setStage({ kind: 'idle' }); disconnect(); }}>
          Disconnect
        </button>
      </div>
    );
  }

  if (stage.kind === 'mismatch') {
    return (
      <div className="ens-gate ens-gate--err">
        <div className="ens-gate__title">✕ Not the owner</div>
        <p className="ens-gate__sub">
          <code>{ensName}</code> resolves to{' '}
          <code>{stage.resolved.slice(0, 8)}…{stage.resolved.slice(-4)}</code>, not your
          connected wallet <code>{stage.address.slice(0, 8)}…{stage.address.slice(-4)}</code>.
          Connect the owner wallet or pick a different slug.
        </p>
        <button type="button" className="ens-gate__btn ens-gate__btn--secondary" onClick={() => disconnect()}>
          Disconnect
        </button>
      </div>
    );
  }

  if (stage.kind === 'error') {
    return (
      <div className="ens-gate ens-gate--err">
        <div className="ens-gate__title">✕ Verification failed</div>
        <p className="ens-gate__sub">{stage.message}</p>
        <button type="button" className="ens-gate__btn ens-gate__btn--secondary" onClick={() => setStage({ kind: 'idle' })}>
          Try again
        </button>
      </div>
    );
  }

  // checking | unowned | owned | signing
  const action = stage.kind === 'signing' ? 'Signing…'
    : stage.kind === 'owned' ? 'Sign claim (you own this name)'
    : stage.kind === 'unowned' ? 'Sign claim (slug is unresolved)'
    : 'Resolving ENS on Sepolia…';

  return (
    <div className={`ens-gate ${stage.kind === 'owned' ? 'ens-gate--ok' : 'ens-gate--idle'}`}>
      <div className="ens-gate__title">
        {address && <>Connected: <code>{address.slice(0, 8)}…{address.slice(-4)}</code></>}
      </div>
      <p className="ens-gate__sub">
        {stage.kind === 'checking' && 'Reading ENS resolver on Sepolia…'}
        {stage.kind === 'unowned' && (<><code>{ensName}</code> isn&apos;t resolved on Sepolia. Sign to register the claim under your wallet.</>)}
        {stage.kind === 'owned' && (<>Your wallet owns <code>{ensName}</code> — sign to bind this agent record to it.</>)}
        {stage.kind === 'signing' && 'Open your wallet and approve the message…'}
      </p>
      <div className="ens-gate__actions">
        <button type="button" className="ens-gate__btn"
                disabled={stage.kind === 'checking' || stage.kind === 'signing'}
                onClick={onSign}>
          {action}
        </button>
        <button type="button" className="ens-gate__btn ens-gate__btn--secondary" onClick={() => disconnect()}>
          Disconnect
        </button>
      </div>
    </div>
  );
}
