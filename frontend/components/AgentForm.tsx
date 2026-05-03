'use client';

import { useEffect, useMemo, useState } from 'react';

import {
  AgentRecord,
  Appetite,
  CreateAgentRequest,
  Profile,
  PublishResponse,
  sibylfi,
} from '@/lib/api';

const TOKENS = ['WETH/USDC', 'WBTC/USDC'];
const APPETITES: Appetite[] = ['conservative', 'balanced', 'aggressive'];

type Status =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'success'; message: string };

const SWING_FIELDS = [
  ['min_dow_bars', 'Min Dow streak (bars)'],
  ['twap_max_deviation', 'Max TWAP deviation'],
  ['sl_pct', 'Stop loss %'],
  ['tp1_rr', 'TP1 R:R'],
  ['tp2_rr', 'TP2 R:R'],
  ['confidence_base', 'Base confidence (bps)'],
  ['confidence_cap', 'Confidence cap (bps)'],
] as const;

const SCALPER_FIELDS = [
  ['mode', 'ML mode (Discovery|Balanced|Conservative)'],
  ['twap_max_deviation', 'Max TWAP deviation'],
  ['sl_pct', 'Stop loss %'],
  ['tp_rr', 'TP R:R'],
  ['btc_crash_pct', 'BTC crash threshold (%)'],
  ['daily_loss_limit_pct', 'Daily loss limit (%)'],
  ['confidence_cap', 'Confidence cap (bps)'],
] as const;

export function AgentForm() {
  const [profile, setProfile] = useState<Profile>('swing');
  const [displayName, setDisplayName] = useState('Trend Hunter');
  const [ensSlug, setEnsSlug] = useState('trend-hunter');
  const [token, setToken] = useState(TOKENS[0]);
  const [appetite, setAppetite] = useState<Appetite>('balanced');
  const [pricePerSignal, setPricePerSignal] = useState(1.0);
  const [params, setParams] = useState<Record<string, string>>({});
  const [defaults, setDefaults] = useState<Record<string, string | number>>({});

  const [agents, setAgents] = useState<AgentRecord[]>([]);
  const [createStatus, setCreateStatus] = useState<Status>({ kind: 'idle' });
  const [publishLog, setPublishLog] = useState<{ id: number; result: PublishResponse }[]>([]);

  // Load defaults whenever profile changes
  useEffect(() => {
    let cancelled = false;
    sibylfi
      .defaultParams(profile)
      .then((res) => {
        if (cancelled) return;
        const flat: Record<string, string | number> = {};
        for (const [k, v] of Object.entries(res.params)) {
          flat[k] = typeof v === 'object' ? JSON.stringify(v) : (v as string | number);
        }
        setDefaults(flat);
        setParams({});
      })
      .catch((e) => setCreateStatus({ kind: 'error', message: `defaults: ${String(e)}` }));
    return () => {
      cancelled = true;
    };
  }, [profile]);

  const refreshList = async () => {
    try {
      const list = await sibylfi.listAgents();
      setAgents(list);
    } catch (e) {
      setCreateStatus({ kind: 'error', message: `list: ${String(e)}` });
    }
  };

  useEffect(() => {
    refreshList();
  }, []);

  const ensName = useMemo(() => `${ensSlug.toLowerCase().replace(/[^a-z0-9-]/g, '')}.sibyl.eth`, [ensSlug]);

  const onCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreateStatus({ kind: 'loading' });

    // Coerce numeric string inputs back to numbers for the params payload
    const numericParams: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(params)) {
      if (v === '' || v == null) continue;
      const asNum = Number(v);
      numericParams[k] = Number.isFinite(asNum) && !Number.isNaN(asNum) && /^[-+]?\d/.test(v) ? asNum : v;
    }

    const req: CreateAgentRequest = {
      display_name: displayName,
      ens_name: ensName,
      profile,
      token,
      appetite,
      price_per_signal_usdc: pricePerSignal,
      params: numericParams,
    };

    try {
      const created = await sibylfi.createAgent(req);
      setCreateStatus({
        kind: 'success',
        message: `created ${created.ens_name} (id=${created.id}) at ${created.address.slice(0, 8)}…`,
      });
      await refreshList();
    } catch (err) {
      setCreateStatus({ kind: 'error', message: String(err) });
    }
  };

  const onPublish = async (id: number) => {
    try {
      const res = await sibylfi.publishCustomSignal(id, token);
      setPublishLog((prev) => [{ id, result: res }, ...prev].slice(0, 6));
    } catch (e) {
      const errResult: PublishResponse = { status: 'no_signal', reason: String(e), signal: null };
      setPublishLog((prev) => [{ id, result: errResult }, ...prev].slice(0, 6));
    }
  };

  const onDelete = async (id: number) => {
    try {
      await sibylfi.deleteAgent(id);
      await refreshList();
    } catch (e) {
      setCreateStatus({ kind: 'error', message: `delete: ${String(e)}` });
    }
  };

  const fields = profile === 'swing' ? SWING_FIELDS : SCALPER_FIELDS;

  return (
    <section className="agent-form">
      <h2>Register a Custom Research Agent</h2>
      <p className="agent-form__sub">
        Pick a strategy profile, override any params, and the orchestrator spins up a wallet-backed
        signed-signal publisher. Built on the same rule engine that powers <code>swing.sibyl.eth</code>{' '}
        and <code>scalper.sibyl.eth</code>.
      </p>

      <div className="agent-form__tabs">
        {(['swing', 'scalper'] as Profile[]).map((p) => (
          <button
            key={p}
            type="button"
            className={`tab ${profile === p ? 'tab--active' : ''}`}
            onClick={() => setProfile(p)}
          >
            {p}
          </button>
        ))}
      </div>

      <form onSubmit={onCreate} className="agent-form__form">
        <div className="row">
          <label>
            <span>Display name</span>
            <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} required />
          </label>
          <label>
            <span>ENS slug</span>
            <input value={ensSlug} onChange={(e) => setEnsSlug(e.target.value)} required />
            <small>{ensName}</small>
          </label>
        </div>

        <div className="row">
          <label>
            <span>Token</span>
            <select value={token} onChange={(e) => setToken(e.target.value)}>
              {TOKENS.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Risk appetite</span>
            <select value={appetite} onChange={(e) => setAppetite(e.target.value as Appetite)}>
              {APPETITES.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Price per signal (USDC)</span>
            <input
              type="number"
              step="0.01"
              min="0.01"
              value={pricePerSignal}
              onChange={(e) => setPricePerSignal(parseFloat(e.target.value) || 0)}
              required
            />
          </label>
        </div>

        <fieldset className="agent-form__params">
          <legend>{profile} params (blank = use default)</legend>
          {fields.map(([key, label]) => (
            <label key={key}>
              <span>{label}</span>
              <input
                placeholder={String(defaults[key] ?? '')}
                value={params[key] ?? ''}
                onChange={(e) => setParams((prev) => ({ ...prev, [key]: e.target.value }))}
              />
            </label>
          ))}
        </fieldset>

        <button type="submit" disabled={createStatus.kind === 'loading'}>
          {createStatus.kind === 'loading' ? 'Registering…' : 'Register agent'}
        </button>

        {createStatus.kind === 'error' && (
          <p className="agent-form__msg agent-form__msg--err">{createStatus.message}</p>
        )}
        {createStatus.kind === 'success' && (
          <p className="agent-form__msg agent-form__msg--ok">{createStatus.message}</p>
        )}
      </form>

      <h3>Registered agents</h3>
      {agents.length === 0 ? (
        <p className="agent-form__empty">No custom agents yet.</p>
      ) : (
        <ul className="agent-form__list">
          {agents.map((a) => (
            <li key={a.id} className="agent-form__row">
              <div className="agent-form__row-meta">
                <strong>{a.display_name}</strong>{' '}
                <code>
                  {a.ens_name} · {a.profile} · {a.appetite}
                </code>
                <small>
                  {a.address.slice(0, 8)}… · {a.token} · {a.price_per_signal_usdc} USDC
                </small>
              </div>
              <div className="agent-form__row-actions">
                <button type="button" onClick={() => onPublish(a.id)}>
                  Publish signal
                </button>
                <button type="button" onClick={() => onDelete(a.id)}>
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {publishLog.length > 0 && (
        <details open>
          <summary>Recent publish results</summary>
          <ul className="agent-form__publog">
            {publishLog.map((entry, i) => (
              <li key={`${entry.id}-${i}`}>
                <code>
                  agent={entry.id} status={entry.result.status}
                  {entry.result.reason ? ` reason=${entry.result.reason}` : ''}
                  {entry.result.signal && typeof entry.result.signal.confidence_bps === 'number'
                    ? ` confidence=${entry.result.signal.confidence_bps}bps`
                    : ''}
                </code>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
