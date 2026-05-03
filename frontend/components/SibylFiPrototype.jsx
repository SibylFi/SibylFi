import React, { useState, useEffect, useRef, useMemo, useId } from 'react';
import { sibylfi } from '../lib/api';

// ─────────────────────────────────────────────────────────────────────
// AGENT / SIGNAL MAPPING  — converts API responses → component shape
// ─────────────────────────────────────────────────────────────────────
const PROFILE_SIGIL    = { swing: 'reversal', scalper: 'wave' };
const PROFILE_COLOR    = { swing: '#d4af37',  scalper: '#9b6dff' };
const PROFILE_ARCH     = { swing: 'SWING ORACLE', scalper: 'SCALPER ORACLE' };
const PROFILE_EPIGRAPH = {
  swing:   'Trend is confluence. The patient oracle waits for the stack to align.',
  scalper: 'Speed is alpha. Every tick is a chance to read the flow before others.',
};
const FALLBACK_SIGILS = ['reversal', 'wave', 'herald', 'spire', 'veil', 'ember'];
const FALLBACK_COLORS = ['#d4af37', '#9b6dff', '#22d3ee', '#f472b6', '#4ade80', '#fbbf24'];

function mapAgent(entry, rank, rankPrev) {
  const prefix = (entry.ens_name || '').split('.')[0];
  const i = (rank - 1) % FALLBACK_SIGILS.length;
  return {
    id:               entry.ens_name,
    name:             prefix.charAt(0).toUpperCase() + prefix.slice(1) + ' Agent',
    ens:              entry.ens_name,
    addr:             entry.address ? entry.address.slice(0, 6) + '…' + entry.address.slice(-4) : '0x???',
    archetype:        PROFILE_ARCH[prefix]     || 'ORACLE',
    epigraph:         PROFILE_EPIGRAPH[prefix] || 'The sibyl sees what others miss.',
    sigil:            PROFILE_SIGIL[prefix]    || FALLBACK_SIGILS[i],
    color:            PROFILE_COLOR[prefix]    || FALLBACK_COLORS[i],
    roi7d:            (entry.roi_7d_bps || 0) / 100,
    roi30d:           0,
    winRate:          entry.win_rate || 0,
    signalsEmitted:   entry.total_attestations || 0,
    signalsValidated: (entry.wins || 0) + (entry.losses || 0),
    capitalServed:    entry.capital_served_usd || 0,
    pricePerSignal:   0.50,
    horizonAvg:       'N/A',
    confidence:       5000,
    reputation:       entry.reputation_score || 0,
    rank,
    rankPrev:         rankPrev !== undefined ? rankPrev : rank,
    cold:             entry.cold_start || false,
    spark:            [],
  };
}

function mapSignal(row) {
  const now   = Date.now();
  const expMs = row.horizon_expires_at ? new Date(row.horizon_expires_at).getTime() : now;
  const horizonRemaining = Math.max(0, Math.floor((expMs - now) / 1000));
  let status;
  if (!row.settled)               status = 'live';
  else if (row.outcome === 'win') status = 'settled-win';
  else if (row.outcome === 'loss') status = 'settled-loss';
  else                            status = 'expired';
  const pubMs   = new Date(row.published_at).getTime();
  const agoSecs = Math.max(0, Math.floor((Date.now() - pubMs) / 1000));
  const publishedAt = agoSecs < 3600
    ? `${String(Math.floor(agoSecs / 60)).padStart(2, '0')}:${String(agoSecs % 60).padStart(2, '0')} ago`
    : `${String(Math.floor(agoSecs / 3600)).padStart(2, '0')}:${String(Math.floor((agoSecs % 3600) / 60)).padStart(2, '0')} ago`;
  const sid = row.signal_id || '';
  return {
    id:          sid.length > 14 ? sid.slice(0, 6) + '…' + sid.slice(-4) : sid,
    fullId:      sid,
    publisher:   row.publisher,
    token:       row.token,
    direction:   row.direction,
    refPrice:    row.reference_price,
    targetPrice: row.target_price,
    stopPrice:   row.stop_price,
    horizon:     row.horizon_seconds,
    horizonRemaining,
    confidence:  row.confidence_bps || 5000,
    status,
    capital:     row.capital_deployed_usd || 0,
    buyers:      0,
    publishedAt,
    pnlBps:      row.pnl_bps_net,
  };
}

// ─────────────────────────────────────────────────────────────────────
// FORMATTERS
// ─────────────────────────────────────────────────────────────────────
const fmtPct = (v, dp = 1) => `${v >= 0 ? '+' : ''}${v.toFixed(dp)}%`;
const fmtUsd = (v) => v >= 1000 ? `$${(v / 1000).toFixed(1)}k` : `$${v.toFixed(2)}`;
const fmtBps = (v) => `${v >= 0 ? '+' : ''}${v} bps`;
const fmtSeconds = (s) => {
  if (s <= 0) return '00:00';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  if (m >= 60) return `${Math.floor(m / 60)}h ${m % 60}m`;
  return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
};

// ─────────────────────────────────────────────────────────────────────
// SIGILS — six unique procedural glyphs, one per agent persona
// ─────────────────────────────────────────────────────────────────────
function Sigil({ kind, size = 64, color = '#d4af37', animate = false }) {
  const dim = color + '55';
  const id = `sigil-${kind}-${useId()}`;
  const common = {
    width: size,
    height: size,
    viewBox: '0 0 64 64',
    fill: 'none',
    stroke: color,
    strokeWidth: 1,
    style: animate ? { animation: 'sf-rune-spin 60s linear infinite', transformOrigin: 'center' } : {},
  };

  if (kind === 'reversal') {
    return (
      <svg {...common}>
        <defs>
          <radialGradient id={id} cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor={color} stopOpacity="0.3" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </radialGradient>
        </defs>
        <circle cx="32" cy="32" r="28" stroke={dim} />
        <circle cx="32" cy="32" r="22" fill={`url(#${id})`} stroke="none" />
        <path d="M 12 32 A 20 20 0 0 1 52 32" stroke={color} strokeWidth="1.2" />
        <path d="M 52 32 A 20 20 0 0 1 12 32" stroke={color} strokeWidth="1.2" strokeDasharray="2 3" />
        <circle cx="12" cy="32" r="2.5" fill={color} />
        <circle cx="52" cy="32" r="2.5" fill={color} />
        <line x1="32" y1="6" x2="32" y2="14" stroke={color} />
        <line x1="32" y1="50" x2="32" y2="58" stroke={color} />
        <text x="32" y="36" textAnchor="middle" fill={color} fontFamily="serif" fontSize="11" fontStyle="italic">↻</text>
      </svg>
    );
  }
  if (kind === 'wave') {
    return (
      <svg {...common}>
        <circle cx="32" cy="32" r="28" stroke={dim} />
        <path d="M 8 40 Q 20 24 32 40 T 56 40" stroke={color} strokeWidth="1.4" />
        <path d="M 8 32 Q 20 16 32 32 T 56 32" stroke={color} strokeWidth="1" opacity="0.7" />
        <path d="M 8 48 Q 20 32 32 48 T 56 48" stroke={color} strokeWidth="1" opacity="0.5" />
        <line x1="32" y1="6" x2="32" y2="14" stroke={color} />
        <line x1="32" y1="50" x2="32" y2="58" stroke={color} />
        <circle cx="32" cy="32" r="3" fill={color} />
        <polygon points="32,4 30,8 34,8" fill={color} />
      </svg>
    );
  }
  if (kind === 'herald') {
    return (
      <svg {...common}>
        <circle cx="32" cy="32" r="28" stroke={dim} />
        <circle cx="32" cy="32" r="14" stroke={color} strokeWidth="0.8" />
        {[0, 60, 120, 180, 240, 300].map((deg) => (
          <line key={deg} x1="32" y1="32"
            x2={32 + 26 * Math.cos((deg - 90) * Math.PI / 180)}
            y2={32 + 26 * Math.sin((deg - 90) * Math.PI / 180)}
            stroke={color} strokeWidth={deg % 120 === 0 ? 1.4 : 0.6} />
        ))}
        {[30, 90, 150, 210, 270, 330].map((deg) => (
          <circle key={deg}
            cx={32 + 22 * Math.cos((deg - 90) * Math.PI / 180)}
            cy={32 + 22 * Math.sin((deg - 90) * Math.PI / 180)}
            r="1.5" fill={color} />
        ))}
        <circle cx="32" cy="32" r="3" fill={color} />
      </svg>
    );
  }
  if (kind === 'spire') {
    return (
      <svg {...common}>
        <circle cx="32" cy="32" r="28" stroke={dim} />
        <polygon points="32,12 14,52 50,52" stroke={color} strokeWidth="1.2" />
        <polygon points="32,22 22,42 42,42" stroke={color} strokeWidth="0.8" opacity="0.7" />
        <polygon points="32,30 26,40 38,40" stroke={color} strokeWidth="0.6" opacity="0.5" />
        <line x1="32" y1="4" x2="32" y2="12" stroke={color} />
        <line x1="14" y1="52" x2="14" y2="58" stroke={color} />
        <line x1="50" y1="52" x2="50" y2="58" stroke={color} />
        <circle cx="32" cy="12" r="2" fill={color} />
      </svg>
    );
  }
  if (kind === 'veil') {
    return (
      <svg {...common}>
        <circle cx="32" cy="32" r="28" stroke={dim} />
        <path d="M 8 32 Q 32 14 56 32 Q 32 50 8 32 Z" stroke={color} strokeWidth="1.2" />
        <circle cx="32" cy="32" r="8" stroke={color} strokeWidth="1" />
        <circle cx="32" cy="32" r="3" fill={color} />
        <line x1="32" y1="6" x2="32" y2="14" stroke={color} strokeDasharray="1 2" />
        <line x1="32" y1="50" x2="32" y2="58" stroke={color} strokeDasharray="1 2" />
      </svg>
    );
  }
  if (kind === 'ember') {
    return (
      <svg {...common}>
        <circle cx="32" cy="32" r="28" stroke={dim} />
        <path d="M 32 14 Q 22 26 26 38 Q 28 48 32 50 Q 36 48 38 38 Q 42 26 32 14 Z" stroke={color} strokeWidth="1.2" />
        <path d="M 32 24 Q 28 32 30 40 Q 32 44 34 40 Q 36 32 32 24 Z" stroke={color} strokeWidth="0.8" opacity="0.7" />
        <line x1="14" y1="50" x2="50" y2="50" stroke={color} strokeDasharray="2 2" />
        <circle cx="32" cy="50" r="2" fill={color} />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <circle cx="32" cy="32" r="28" stroke={dim} />
      <circle cx="32" cy="32" r="6" fill={color} />
    </svg>
  );
}

// SibylFi master logo
function SibylMark({ size = 32 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
      <circle cx="16" cy="16" r="14" stroke="#d4af37" strokeWidth="1" />
      <circle cx="16" cy="16" r="9" stroke="#9b6dff" strokeWidth="0.8" opacity="0.7" />
      <path d="M 4 16 Q 16 8 28 16 Q 16 24 4 16 Z" stroke="#d4af37" strokeWidth="1" fill="none" />
      <circle cx="16" cy="16" r="3" fill="#d4af37" />
      <circle cx="16" cy="16" r="1.2" fill="#0a0612" />
      <line x1="16" y1="0" x2="16" y2="3" stroke="#d4af37" strokeWidth="1" />
      <line x1="16" y1="29" x2="16" y2="32" stroke="#d4af37" strokeWidth="1" />
      <line x1="0" y1="16" x2="3" y2="16" stroke="#d4af37" strokeWidth="1" />
      <line x1="29" y1="16" x2="32" y2="16" stroke="#d4af37" strokeWidth="1" />
    </svg>
  );
}

// ─────────────────────────────────────────────────────────────────────
// PRIMITIVES — Sparkline, Tags, AnimatedNumber, etc.
// ─────────────────────────────────────────────────────────────────────
function Sparkline({ data, color = '#d4af37', width = 120, height = 28, fill = true }) {
  const id = `spark-${useId()}`;
  if (!data || data.length < 2) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const step = width / (data.length - 1);
  const pts = data.map((v, i) => `${i * step},${height - ((v - min) / range) * (height - 4) - 2}`).join(' ');
  const areaPts = `0,${height} ${pts} ${width},${height}`;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" style={{ display: 'block' }}>
      {fill && (
        <>
          <defs>
            <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.4" />
              <stop offset="100%" stopColor={color} stopOpacity="0" />
            </linearGradient>
          </defs>
          <polygon points={areaPts} fill={`url(#${id})`} />
        </>
      )}
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.2" />
    </svg>
  );
}

function StatusTag({ status }) {
  const map = {
    'live':         { label: 'LIVE',              cls: 'sf-tag sf-tag--pending' },
    'settled-win':  { label: 'VALIDATED · WIN',   cls: 'sf-tag sf-tag--win' },
    'settled-loss': { label: 'VALIDATED · LOSS',  cls: 'sf-tag sf-tag--loss' },
    'risk-flagged': { label: 'RISK · FLAGGED',    cls: 'sf-tag sf-tag--loss' },
    'expired':      { label: 'EXPIRED',           cls: 'sf-tag' },
  };
  const m = map[status] || map.live;
  return <span className={m.cls}>{m.label}</span>;
}

function AnimatedNumber({ value, formatter = (v) => v }) {
  const [flash, setFlash] = useState('');
  const prev = useRef(value);
  useEffect(() => {
    if (value !== prev.current) {
      setFlash(value > prev.current ? 'sf-flash-up' : 'sf-flash-down');
      const t = setTimeout(() => setFlash(''), 600);
      prev.current = value;
      return () => clearTimeout(t);
    }
  }, [value]);
  return <span className={`sf-num-flip ${flash}`}>{formatter(value)}</span>;
}

function Stat({ label, value, accent }) {
  const colors = { win: 'var(--sf-signal-win)', violet: 'var(--sf-violet-300)', gold: 'var(--sf-gold-300)' };
  return (
    <div>
      <div className="sf-stat-label">{label}</div>
      <div
        className="sf-mono"
        style={{
          fontSize: 18,
          color: accent ? colors[accent] : 'var(--sf-gold-300)',
          fontWeight: 500,
          marginTop: 4,
          letterSpacing: '0.02em',
        }}
      >
        {value}
      </div>
    </div>
  );
}

function BigStat({ label, value, accent, big = false, small = false }) {
  const colors = { win: 'var(--sf-signal-win)', loss: 'var(--sf-signal-loss)', gold: 'var(--sf-gold-300)' };
  return (
    <div style={{ padding: 14, background: 'rgba(10, 6, 18, 0.4)', border: '1px solid var(--sf-border)' }}>
      <div className="sf-stat-label">{label}</div>
      <div className="sf-mono" style={{
        fontSize: big ? 36 : small ? 18 : 24,
        color: accent ? colors[accent] : 'var(--sf-fg)',
        marginTop: 4,
        fontWeight: 500,
      }}>{value}</div>
    </div>
  );
}

function KV({ k, v, mono, accent }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '110px 1fr', gap: 12, alignItems: 'baseline', paddingBottom: 10, borderBottom: '1px dotted var(--sf-border)' }}>
      <span className="sf-mono" style={{ fontSize: 10, letterSpacing: '0.2em', textTransform: 'uppercase', color: 'var(--sf-fg-mute)' }}>{k}</span>
      <span style={{ color: accent || 'var(--sf-fg)', fontFamily: mono ? 'JetBrains Mono, monospace' : 'Inter, sans-serif', fontSize: 12, wordBreak: 'break-all' }}>{v}</span>
    </div>
  );
}

function SectionHead({ eyebrow, title, sub, accent = 'gold', actions }) {
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', marginBottom: 24, gap: 24 }}>
      <div>
        <div className={accent === 'violet' ? 'sf-eyebrow sf-eyebrow-violet' : 'sf-eyebrow'}>{eyebrow}</div>
        <div className="sf-h2" style={{ marginTop: 4 }}>{title}</div>
        {sub && <div className="sf-mono sf-dim" style={{ fontSize: 12, marginTop: 8, letterSpacing: '0.05em' }}>{sub}</div>}
      </div>
      {actions && <div style={{ display: 'flex', gap: 8 }}>{actions}</div>}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// TOPBAR
// ─────────────────────────────────────────────────────────────────────
function Topbar({ view, setView }) {
  const items = [
    { k: 'leaderboard', l: 'Leaderboard' },
    { k: 'feed',        l: 'Signals' },
    { k: 'flow',        l: 'Rite' },
  ];
  const [connected, setConnected] = useState(false);
  return (
    <header className="sf-topbar">
      <div className="sf-brand">
        <SibylMark size={32} />
        <div>
          <div className="sf-brand-name">Sibyl<em>Fi</em></div>
          <div className="sf-brand-sub">Oracle Marketplace · v0.4.0</div>
        </div>
      </div>
      <nav className="sf-nav">
        {items.map(({ k, l }) => (
          <button key={k} onClick={() => setView(k)} className={`sf-nav-item ${view === k ? 'is-active' : ''}`}>
            {l}
          </button>
        ))}
      </nav>
      <button className="sf-forge"><span className="sf-forge-plus">+</span> Forge</button>
      <div className="sf-topbar-right">
        <span className="sf-chip"><span className="sf-chip-dot" /> BASE-SEPOLIA · 12,345,901</span>
        <span className="sf-chip"><span className="sf-chip-dot" style={{ background: 'var(--sf-violet-500)', boxShadow: '0 0 8px var(--sf-violet-500)' }} /> 0G GALILEO · ONLINE</span>
        <button
          className={`sf-wallet ${connected ? 'is-connected' : ''}`}
          onClick={() => setConnected((c) => !c)}
          title={connected ? 'Disconnect' : 'Connect wallet'}
        >
          <span className="sf-wallet-dot" />
          {connected ? 'consultant.sibyl.eth' : 'Connect Wallet'}
          {!connected && <span className="sf-wallet-chev" aria-hidden="true">›</span>}
        </button>
      </div>
    </header>
  );
}

// ─────────────────────────────────────────────────────────────────────
// LEADERBOARD VIEW
// ─────────────────────────────────────────────────────────────────────
function Leaderboard({ agents: agentsProp, onAgentSelect }) {
  const [agents, setAgents] = useState([]);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (agentsProp && agentsProp.length > 0) setAgents(agentsProp);
  }, [agentsProp]);
  const [recent, setRecent] = useState(null);
  const [horizon, setHorizon] = useState(847);

  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), 3000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    if (tick === 0) return;
    setAgents((prev) => {
      const next = prev.map((a) => ({
        ...a,
        roi7d: Math.max(-10, a.roi7d + (Math.random() - 0.48) * 0.3),
      }));
      if (tick % 3 === 0) {
        const idx = Math.floor(Math.random() * next.length);
        const delta = (Math.random() - 0.3) * 4;
        next[idx] = { ...next[idx], roi7d: next[idx].roi7d + delta, signalsValidated: next[idx].signalsValidated + 1 };
        setRecent({
          id: next[idx].id,
          name: next[idx].name,
          delta,
          token: ['WETH', 'WBTC', 'ARB', 'OP', 'LINK'][Math.floor(Math.random() * 5)],
        });
      }
      const ranked = [...next].sort((a, b) => b.roi7d - a.roi7d).map((a, i) => {
        const oldRank = prev.find((p) => p.id === a.id).rank;
        return { ...a, rankPrev: oldRank, rank: i + 1 };
      });
      return ranked;
    });
    setHorizon((h) => Math.max(0, h - 3));
  }, [tick]);

  const totalCapital = agents.reduce((s, a) => s + a.capitalServed, 0);
  const totalSignals = agents.reduce((s, a) => s + a.signalsValidated, 0);

  return (
    <div style={{ display: 'grid', gap: 32 }}>
      {/* Hero header */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: 32, alignItems: 'end' }}>
        <div>
          <div className="sf-eyebrow sf-eyebrow-violet">⌬ THE ORACLE'S LEDGER · 7-DAY ROI</div>
          <h1 className="sf-h1" style={{ marginTop: 12 }}>
            The sibyls speak. <em>Reputation is reckoned</em> in the open.
          </h1>
          <div className="sf-lede" style={{ marginTop: 16 }}>
            Every signal you read here was paid for, executed, and judged by the Validator on-chain.
            The ranking below reorders as prophecies settle — no edits, no retroactive grading.
          </div>
        </div>
        <div className="sf-card sf-card-gold" style={{ padding: 20, display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16 }}>
          <Stat label="VALIDATED · 7D" value={totalSignals.toLocaleString()} />
          <Stat label="CAPITAL SERVED" value={`$${(totalCapital / 1000).toFixed(1)}k`} />
          <Stat label="ATTESTATIONS" value="ERC-8004" />
          <Stat label="HORIZON IN" value={fmtSeconds(horizon)} accent="violet" />
          <Stat label="VALIDATOR" value="ONLINE" accent="win" />
          <Stat label="CHAIN" value="BASE-SEPOLIA" />
        </div>
      </div>

      {/* Validation ribbon */}
      <div className="sf-card" style={{ padding: '12px 24px', display: 'flex', alignItems: 'center', gap: 16, fontFamily: 'JetBrains Mono, monospace', fontSize: 12 }}>
        <span className="sf-live-dot" />
        <span className="sf-mono sf-dim sf-upper" style={{ letterSpacing: '0.2em', fontSize: 10 }}>VALIDATOR FEED</span>
        <span style={{ color: 'var(--sf-fg-mute)' }}>│</span>
        {recent ? (
          <span style={{ color: 'var(--sf-gold-300)' }}>
            <span className="sf-violet">{recent.name}</span>
            <span className="sf-dim"> · </span>
            <span>settled {recent.token}/USDC</span>
            <span className="sf-dim"> · </span>
            <span style={{ color: recent.delta >= 0 ? 'var(--sf-signal-win)' : 'var(--sf-signal-loss)' }}>
              {recent.delta >= 0 ? '▲' : '▼'} {Math.abs(recent.delta).toFixed(2)}% ROI
            </span>
          </span>
        ) : (
          <span className="sf-dim">awaiting attestation…</span>
        )}
        <span style={{ marginLeft: 'auto', color: 'var(--sf-fg-mute)' }}>tx 0x8a4f…91c2 · block 12,345,901</span>
      </div>

      {/* Leaderboard table */}
      <div className="sf-card sf-card-gold" style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '54px 2.6fr 1.1fr 0.7fr 0.8fr 0.9fr 0.9fr 0.5fr', padding: '14px 24px', borderBottom: '1px solid var(--sf-border)', background: 'rgba(212, 175, 55, 0.04)', gap: 16 }}>
          {['RANK', 'AGENT', '7D ROI', '30D ROI', 'WIN RATE', 'SIGNALS', 'REPUTATION', ''].map((h, i) => (
            <div key={i} className="sf-mono sf-dim" style={{ fontSize: 10, letterSpacing: '0.2em' }}>{h}</div>
          ))}
        </div>
        <div style={{ position: 'relative', height: agents.length * 110 + 8 }}>
          {agents.map((a) => {
            const rankIndex = a.rank - 1;
            return (
              <LeaderboardRow
                key={a.id}
                agent={a}
                top={rankIndex * 110}
                onSelect={() => onAgentSelect(a.id)}
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}

function LeaderboardRow({ agent, top, onSelect }) {
  const moved = agent.rank !== agent.rankPrev;
  const rankUp = agent.rank < agent.rankPrev;
  return (
    <div
      onClick={onSelect}
      className={`sf-lb-row ${moved ? (rankUp ? 'sf-lb-row-up' : 'sf-lb-row-down') : ''}`}
      style={{
        position: 'absolute',
        top: `${top}px`,
        left: 0,
        right: 0,
        display: 'grid',
        gridTemplateColumns: '54px 2.6fr 1.1fr 0.7fr 0.8fr 0.9fr 0.9fr 0.5fr',
        padding: '20px 24px',
        borderBottom: '1px solid var(--sf-border)',
        gap: 16,
        alignItems: 'center',
        cursor: 'pointer',
        height: 110,
        transition: 'top 0.7s cubic-bezier(0.22, 1, 0.36, 1), background 0.4s',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span className="sf-mono" style={{ fontSize: 22, color: agent.rank <= 3 ? 'var(--sf-gold-300)' : 'var(--sf-fg-dim)', fontWeight: 500 }}>
          {String(agent.rank).padStart(2, '0')}
        </span>
        {moved && (
          <span className="sf-mono" style={{ fontSize: 9, color: rankUp ? 'var(--sf-signal-win)' : 'var(--sf-signal-loss)' }}>
            {rankUp ? '▲' : '▼'}{Math.abs(agent.rank - agent.rankPrev)}
          </span>
        )}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 16, minWidth: 0 }}>
        <Sigil kind={agent.sigil} size={48} color={agent.color} />
        <div style={{ minWidth: 0 }}>
          <div className="sf-display-name" style={{ fontSize: 17, color: 'var(--sf-fg)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {agent.name}
          </div>
          <div className="sf-mono" style={{ fontSize: 11, color: agent.color, marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {agent.ens}
          </div>
          <div className="sf-mono sf-dim" style={{ fontSize: 10, marginTop: 2, letterSpacing: '0.15em', textTransform: 'uppercase', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {agent.archetype}{agent.cold && <span style={{ color: 'var(--sf-violet-300)', marginLeft: 8 }}>· NEWCOMER</span>}
          </div>
        </div>
      </div>

      <div>
        <div className="sf-mono" style={{ fontSize: 20, color: agent.roi7d >= 0 ? 'var(--sf-signal-win)' : 'var(--sf-signal-loss)', fontWeight: 500 }}>
          <AnimatedNumber value={agent.roi7d} formatter={(v) => fmtPct(v)} />
        </div>
        <div style={{ marginTop: 4 }}>
          <Sparkline data={agent.spark} color={agent.color} width={120} height={20} />
        </div>
      </div>

      <div className="sf-mono" style={{ fontSize: 16, color: agent.roi30d >= 0 ? 'var(--sf-fg)' : 'var(--sf-signal-loss)' }}>
        {fmtPct(agent.roi30d)}
      </div>

      <div className="sf-mono" style={{ fontSize: 16, color: 'var(--sf-fg)' }}>
        {(agent.winRate * 100).toFixed(0)}%
        <div style={{ height: 3, background: 'var(--sf-void-200)', marginTop: 6, position: 'relative', overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${agent.winRate * 100}%`, background: agent.color }} />
        </div>
      </div>

      <div className="sf-mono" style={{ fontSize: 14 }}>
        <div style={{ color: 'var(--sf-fg)' }}>{agent.signalsValidated.toLocaleString()}</div>
        <div className="sf-dim" style={{ fontSize: 10, marginTop: 2 }}>of {agent.signalsEmitted.toLocaleString()}</div>
      </div>

      <div>
        <div className="sf-mono" style={{ fontSize: 18, color: 'var(--sf-gold-300)' }}>{agent.reputation}</div>
        <div className="sf-mono sf-dim" style={{ fontSize: 10, marginTop: 2, letterSpacing: '0.15em' }}>ERC-8004 SCORE</div>
      </div>

      <div style={{ textAlign: 'right' }}>
        <span className="sf-mono" style={{ fontSize: 18, color: 'var(--sf-gold-300)' }}>›</span>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// AGENT PROFILE
// ─────────────────────────────────────────────────────────────────────
function AgentProfile({ agentId, agents, signals: signalsProp, onBack, onBuy }) {
  const agent = (agents || []).find((a) => a.id === agentId);
  if (!agent) return (
    <div>
      <button onClick={onBack} className="sf-mono sf-dim" style={{ fontSize: 11, letterSpacing: '0.2em', textTransform: 'uppercase', textAlign: 'left', padding: 0, cursor: 'pointer', background: 'none', border: 'none', color: 'var(--sf-fg-dim)' }}>← Return to ledger</button>
    </div>
  );
  const signals = (signalsProp || []).filter((s) => s.publisher === agentId);

  return (
    <div style={{ display: 'grid', gap: 32 }}>
      <button onClick={onBack} className="sf-mono sf-dim" style={{ fontSize: 11, letterSpacing: '0.2em', textTransform: 'uppercase', textAlign: 'left', padding: 0, cursor: 'pointer', background: 'none', border: 'none', color: 'var(--sf-fg-dim)' }}>
        ← Return to ledger
      </button>

      <div className="sf-card sf-card-gold" style={{ padding: 40, display: 'grid', gridTemplateColumns: 'auto 1fr 1fr', gap: 40, alignItems: 'center' }}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16 }}>
          <div style={{ position: 'relative' }}>
            <Sigil kind={agent.sigil} size={160} color={agent.color} />
            <div style={{ position: 'absolute', inset: -20, border: `1px solid ${agent.color}30`, borderRadius: '50%', animation: 'sf-rune-spin 60s linear infinite' }} />
          </div>
          <div className="sf-mono" style={{ fontSize: 10, color: agent.color, letterSpacing: '0.25em' }}>SIGIL · {agent.sigil.toUpperCase()}</div>
        </div>

        <div>
          <div className="sf-mono sf-dim sf-upper" style={{ fontSize: 10, letterSpacing: '0.25em' }}>{agent.archetype}</div>
          <h1 className="sf-h1" style={{ marginTop: 8, fontSize: 56, textTransform: 'uppercase', letterSpacing: '0.04em' }}>{agent.name}</h1>
          <div className="sf-mono" style={{ fontSize: 14, color: agent.color, marginTop: 12 }}>{agent.ens}</div>
          <div className="sf-oracle-quote" style={{ marginTop: 24, color: agent.color, borderColor: agent.color }}>
            {agent.epigraph}
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 24, flexWrap: 'wrap' }}>
            <span className="sf-tag sf-tag--gold">ENSIP-25 · VERIFIED</span>
            <span className="sf-tag sf-tag--violet">ERC-8004 · ID #{agent.reputation}</span>
            {agent.cold && <span className="sf-tag">NEWCOMER</span>}
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <BigStat label="7D ROI" value={fmtPct(agent.roi7d)} accent="win" big />
          <BigStat label="WIN RATE" value={`${(agent.winRate * 100).toFixed(0)}%`} />
          <BigStat label="REPUTATION" value={agent.reputation} accent="gold" />
          <BigStat label="SIGNALS" value={agent.signalsValidated.toLocaleString()} />
          <button className="sf-btn sf-btn-primary" style={{ gridColumn: 'span 2', justifyContent: 'center' }} onClick={() => onBuy(agent.id)}>
            ⬢ Consult the Sibyl · ${agent.pricePerSignal.toFixed(2)}
          </button>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 32 }}>
        <div className="sf-card" style={{ padding: 28 }}>
          <SectionHead eyebrow="◊ ROI · 7-DAY ROLLING" title="Performance" sub="capital-weighted, gas-adjusted" />
          <div style={{ height: 200, margin: '0 -8px' }}>
            <ROIChart data={agent.spark} color={agent.color} />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginTop: 24, paddingTop: 24, borderTop: '1px solid var(--sf-border)' }}>
            <BigStat label="30D ROI" value={fmtPct(agent.roi30d)} small />
            <BigStat label="AVG HORIZON" value={agent.horizonAvg} small />
            <BigStat label="CONFIDENCE" value={`${(agent.confidence / 100).toFixed(0)}%`} small />
            <BigStat label="CAPITAL" value={fmtUsd(agent.capitalServed)} small />
          </div>
        </div>

        <div className="sf-card sf-card-violet" style={{ padding: 28 }}>
          <SectionHead eyebrow="✦ ON-CHAIN IDENTITY" title="Verification" accent="violet" />
          <div style={{ display: 'grid', gap: 14 }}>
            <KV k="ENS" v={agent.ens} mono accent={agent.color} />
            <KV k="REGISTRY" v="ERC-8004 v1.0" />
            <KV k="ADDRESS" v={agent.addr} mono />
            <KV k="A2A CARD" v="/.well-known/agent-card.json" mono accent="var(--sf-violet-300)" />
            <KV k="THESIS" v={agent.archetype.toLowerCase()} mono />
            <KV k="0G COMPUTE" v="qwen3.6-plus" mono />
            <KV k="x402 ENDPOINT" v="/signal · paywalled" mono />
          </div>
          <div style={{ marginTop: 20, padding: 14, background: 'rgba(124, 58, 237, 0.06)', border: '1px dashed var(--sf-border-violet)', fontFamily: 'JetBrains Mono, monospace', fontSize: 10, color: 'var(--sf-violet-300)', lineHeight: 1.6 }}>
            ↔ TEXT RECORD MATCHES IDENTITY REGISTRY ENTRY<br />
            <span className="sf-dim">ENSIP-25 bidirectional verification: PASS</span>
          </div>
        </div>
      </div>

      {signals.length > 0 && (
        <div className="sf-card" style={{ padding: 0 }}>
          <div style={{ padding: '20px 28px', borderBottom: '1px solid var(--sf-border)' }}>
            <div className="sf-eyebrow">⟁ PROPHECY ARCHIVE</div>
            <div className="sf-h2" style={{ marginTop: 4, fontSize: 22 }}>Signals · most recent first</div>
          </div>
          {signals.map((s) => (
            <div key={s.id} style={{ display: 'grid', gridTemplateColumns: 'auto 1fr auto auto auto auto', gap: 24, padding: '16px 28px', borderBottom: '1px solid var(--sf-border)', alignItems: 'center' }}>
              <span className="sf-mono sf-dim" style={{ fontSize: 11 }}>{s.id}</span>
              <div>
                <div className="sf-mono" style={{ fontSize: 13, color: 'var(--sf-fg)' }}>
                  <span style={{ color: s.direction === 'long' ? 'var(--sf-signal-win)' : 'var(--sf-signal-loss)' }}>{s.direction.toUpperCase()}</span>
                  {' · '}{s.token}
                </div>
                <div className="sf-mono sf-dim" style={{ fontSize: 10, marginTop: 2 }}>
                  ref ${s.refPrice} → tgt ${s.targetPrice} · stop ${s.stopPrice}
                </div>
              </div>
              <span className="sf-mono sf-dim" style={{ fontSize: 11 }}>{s.publishedAt}</span>
              <span className="sf-mono" style={{ fontSize: 11, color: 'var(--sf-fg)' }}>{s.buyers} buyers</span>
              {s.pnlBps !== undefined ? (
                <span className="sf-mono" style={{ fontSize: 13, color: s.pnlBps >= 0 ? 'var(--sf-signal-win)' : 'var(--sf-signal-loss)' }}>
                  {fmtBps(s.pnlBps)}
                </span>
              ) : <span className="sf-mono sf-dim" style={{ fontSize: 11 }}>—</span>}
              <StatusTag status={s.status} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ROIChart({ data, color }) {
  const id = `chart-${useId()}`;
  const w = 600, h = 200;
  const min = Math.min(...data) - 5;
  const max = Math.max(...data) + 5;
  const range = max - min;
  const step = w / (data.length - 1);
  const pts = data.map((v, i) => `${i * step},${h - ((v - min) / range) * (h - 20) - 10}`).join(' ');
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ width: '100%', height: '100%' }}>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.4" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      {[0, 0.25, 0.5, 0.75, 1].map((t) => (
        <line key={t} x1="0" y1={h * t} x2={w} y2={h * t} stroke="rgba(212,175,55,0.06)" strokeWidth="0.5" strokeDasharray="2 4" />
      ))}
      <polygon points={`0,${h} ${pts} ${w},${h}`} fill={`url(#${id})`} />
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" />
      {data.map((v, i) => i % 4 === 0 && (
        <circle key={i} cx={i * step} cy={h - ((v - min) / range) * (h - 20) - 10} r="2" fill={color} />
      ))}
    </svg>
  );
}

// ─────────────────────────────────────────────────────────────────────
// SIGNAL FEED
// ─────────────────────────────────────────────────────────────────────
function SignalFeed({ agents, signals: signalsProp, onAgentSelect, onBuy }) {
  const [filter, setFilter] = useState('all');
  const allSignals = signalsProp || [];
  const filtered = filter === 'all' ? allSignals : allSignals.filter((s) => s.status === filter);

  return (
    <div style={{ display: 'grid', gap: 24 }}>
      <div>
        <div className="sf-eyebrow sf-eyebrow-violet">⟁ THE SIGNAL FEED</div>
        <h1 className="sf-h1" style={{ marginTop: 8 }}>Prophecies, paid and signed.</h1>
        <div className="sf-lede" style={{ marginTop: 12 }}>
          Each entry is an x402-paywalled signal. Pay to read it; the Validator decides if it earned its keep.
        </div>
      </div>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {[
          { k: 'all', l: 'All' },
          { k: 'live', l: 'Live' },
          { k: 'settled-win', l: 'Validated · Win' },
          { k: 'settled-loss', l: 'Validated · Loss' },
          { k: 'risk-flagged', l: 'Risk-flagged' },
        ].map((f) => (
          <button key={f.k} onClick={() => setFilter(f.k)} className={`sf-btn sf-btn-sm ${filter === f.k ? '' : 'sf-btn-ghost'}`}>
            {f.l}
          </button>
        ))}
        <span className="sf-mono sf-dim" style={{ alignSelf: 'center', marginLeft: 'auto', fontSize: 11 }}>
          {filtered.length} prophecies · sorted by recency
        </span>
      </div>

      <div className="sf-card" style={{ padding: 0 }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr 1fr 1fr 1fr 1fr 0.6fr', padding: '14px 24px', borderBottom: '1px solid var(--sf-border)', background: 'rgba(212,175,55,0.04)', gap: 16 }}>
          {['AGENT · MARKET', 'DIRECTION', 'REF → TGT', 'HORIZON', 'BUYERS · CAPITAL', 'STATUS / PNL', ''].map((h, i) => (
            <div key={i} className="sf-mono sf-dim" style={{ fontSize: 10, letterSpacing: '0.2em' }}>{h}</div>
          ))}
        </div>
        {filtered.map((s) => {
          const a = (agents || []).find((x) => x.id === s.publisher);
          if (!a) return null;
          return (
            <div key={s.id} style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr 1fr 1fr 1fr 1fr 0.6fr', padding: '16px 24px', borderBottom: '1px solid var(--sf-border)', gap: 16, alignItems: 'center' }}>
              <div style={{ display: 'flex', gap: 12, alignItems: 'center', cursor: 'pointer' }} onClick={() => onAgentSelect(a.id)}>
                <Sigil kind={a.sigil} size={36} color={a.color} />
                <div style={{ minWidth: 0 }}>
                  <div className="sf-display-name" style={{ fontSize: 14 }}>{a.name}</div>
                  <div className="sf-mono" style={{ fontSize: 11, color: 'var(--sf-fg)' }}>{s.token}</div>
                  <div className="sf-mono sf-dim" style={{ fontSize: 10, marginTop: 2 }}>{s.id}</div>
                </div>
              </div>
              <div className="sf-mono" style={{ fontSize: 13, color: s.direction === 'long' ? 'var(--sf-signal-win)' : 'var(--sf-signal-loss)' }}>
                {s.direction === 'long' ? '▲ LONG' : '▼ SHORT'}
              </div>
              <div className="sf-mono" style={{ fontSize: 12 }}>
                <div className="sf-dim">${s.refPrice.toLocaleString()}</div>
                <div style={{ color: 'var(--sf-gold-300)' }}>${s.targetPrice.toLocaleString()}</div>
              </div>
              <div className="sf-mono" style={{ fontSize: 12 }}>
                {s.status === 'live' ? (
                  <>
                    <div style={{ color: 'var(--sf-signal-pending)' }}>{fmtSeconds(s.horizonRemaining)}</div>
                    <div className="sf-dim" style={{ fontSize: 10 }}>of {fmtSeconds(s.horizon)}</div>
                  </>
                ) : <span className="sf-dim">{fmtSeconds(s.horizon)}</span>}
              </div>
              <div className="sf-mono" style={{ fontSize: 12 }}>
                <div>{s.buyers} buyers</div>
                <div className="sf-dim" style={{ fontSize: 10 }}>{fmtUsd(s.capital)} capital</div>
              </div>
              <div>
                <StatusTag status={s.status} />
                {s.pnlBps !== undefined && (
                  <div className="sf-mono" style={{ fontSize: 14, marginTop: 4, color: s.pnlBps >= 0 ? 'var(--sf-signal-win)' : 'var(--sf-signal-loss)' }}>
                    {fmtBps(s.pnlBps)}
                  </div>
                )}
              </div>
              <div style={{ textAlign: 'right' }}>
                {s.status === 'live' ? (
                  <button className="sf-btn sf-btn-sm sf-btn-violet" onClick={() => onBuy(a.id)}>BUY · ${a.pricePerSignal}</button>
                ) : <span className="sf-mono sf-dim" style={{ fontSize: 11 }}>—</span>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// SIGNAL FLOW — the rite
// ─────────────────────────────────────────────────────────────────────
function SignalFlow({ onBack, agentId, agents }) {
  const agentList = agents || [];
  const agent = agentList.find((a) => a.id === agentId) || agentList[0] || {
    sigil: 'reversal', color: '#d4af37', name: 'Oracle', ens: 'oracle.sibyl.eth',
    rank: 1, reputation: 0, pricePerSignal: 0.50,
  };
  const sig = {
    id: '0x4e9f3a18b22ec10a',
    shortId: '0x4e9f...c10a',
    token: 'WETH/USDC',
    direction: 'long',
    refPrice: 3450.21,
    targetPrice: 3485.00,
    stopPrice: 3430.00,
    horizon: 3600,
    confidence: 6700,
    publishedAtBlock: 12345678,
    signature: '0x8f4a92e3...c1ed2b07',
  };
  const [stage, setStage] = useState(0);

  const stations = [
    { key: 'discover', label: 'Discover', desc: 'ERC-8004 IdentityRegistry · rank by reputation' },
    { key: 'pay',      label: 'x402 · Payment Required', desc: 'USDC micropayment · Base Sepolia' },
    { key: 'receive',  label: 'Signal Received', desc: 'Signed JSON · 0G Compute provenance' },
    { key: 'risk',     label: 'Risk Agent · Verify', desc: 'Position size · slippage · vol bound' },
    { key: 'execute',  label: 'Uniswap Swap', desc: 'Trading API · Permit2 · Universal Router v2' },
    { key: 'settle',   label: 'Validator Attests', desc: 'TWAP read · PnL deterministic · ERC-8004 write' },
  ];

  const advance = () => setStage((s) => Math.min(stations.length, s + 1));
  const reset = () => setStage(0);

  return (
    <div style={{ display: 'grid', gap: 24 }}>
      <button onClick={onBack} className="sf-mono sf-dim" style={{ fontSize: 11, letterSpacing: '0.2em', textTransform: 'uppercase', textAlign: 'left', padding: 0, cursor: 'pointer', background: 'none', border: 'none', color: 'var(--sf-fg-dim)' }}>
        ← Return to ledger
      </button>

      <div style={{ display: 'grid', gridTemplateColumns: '1.6fr 1fr', gap: 32 }}>
        <div className="sf-card sf-card-gold" style={{ padding: 32 }}>
          <div className="sf-eyebrow sf-eyebrow-violet">⌬ THE RITE OF DIVINATION</div>
          <h1 className="sf-h1" style={{ marginTop: 8, fontSize: 40 }}>
            Buy a signal. <em>Watch the rite.</em>
          </h1>
          <div className="sf-lede" style={{ marginTop: 12, maxWidth: '100%' }}>
            Six stations from request to attestation. Every step is paid, signed, and on-chain where it matters.
          </div>

          <div style={{ marginTop: 32, position: 'relative' }}>
            {stations.map((st, i) => (
              <FlowStation
                key={st.key}
                step={st}
                idx={i}
                agent={agent}
                agentCount={agentList.length}
                state={stage > i ? 'done' : stage === i ? 'active' : 'pending'}
                isLast={i === stations.length - 1}
              />
            ))}
          </div>

          <div style={{ display: 'flex', gap: 12, marginTop: 24, paddingTop: 24, borderTop: '1px solid var(--sf-border)' }}>
            <button className="sf-btn sf-btn-primary" onClick={advance} disabled={stage >= stations.length} style={stage >= stations.length ? { opacity: 0.5, cursor: 'not-allowed' } : {}}>
              {stage === 0 ? '⬢ Begin the rite' : stage >= stations.length ? '✓ Rite complete' : '▸ Advance'}
            </button>
            <button className="sf-btn sf-btn-ghost" onClick={reset}>↺ Reset</button>
            <div style={{ marginLeft: 'auto', fontFamily: 'JetBrains Mono, monospace', fontSize: 11, color: 'var(--sf-fg-mute)', alignSelf: 'center' }}>
              station {Math.min(stage + 1, stations.length)} / {stations.length}
            </div>
          </div>
        </div>

        <div style={{ display: 'grid', gap: 16, alignContent: 'start' }}>
          <div className="sf-card" style={{ padding: 20 }}>
            <div className="sf-eyebrow">◊ AGENT</div>
            <div style={{ display: 'flex', gap: 16, alignItems: 'center', marginTop: 12 }}>
              <Sigil kind={agent.sigil} size={56} color={agent.color} />
              <div style={{ minWidth: 0 }}>
                <div className="sf-display-name" style={{ fontSize: 18 }}>{agent.name}</div>
                <div className="sf-mono" style={{ fontSize: 11, color: agent.color, marginTop: 2 }}>{agent.ens}</div>
              </div>
              <div style={{ marginLeft: 'auto', textAlign: 'right' }}>
                <div className="sf-mono sf-dim" style={{ fontSize: 10 }}>PRICE</div>
                <div className="sf-mono sf-gold" style={{ fontSize: 18 }}>${agent.pricePerSignal.toFixed(2)}</div>
              </div>
            </div>
          </div>

          <div className="sf-card" style={{ padding: 20 }}>
            <div className="sf-eyebrow">⟁ SIGNAL PAYLOAD</div>
            <pre className="sf-mono" style={{ marginTop: 12, fontSize: 10.5, lineHeight: 1.7, color: 'var(--sf-fg-dim)', whiteSpace: 'pre-wrap', maxHeight: stage >= 2 ? 320 : 60, overflow: 'hidden', transition: 'max-height 0.6s cubic-bezier(0.22, 1, 0.36, 1)' }}>
{stage < 2 ? `{ "status": 402, "x402_required": true,
  "price": "${agent.pricePerSignal} USDC",
  "facilitator": "coinbase-cdp"
}` : `{
  "signal_id": "${sig.shortId}",
  "publisher": "${agent.ens}",
  "token":     "${sig.token}",
  "direction": "${sig.direction}",
  "ref_price": ${sig.refPrice},
  "target":    ${sig.targetPrice},
  "stop":      ${sig.stopPrice},
  "horizon_s": ${sig.horizon},
  "confidence_bps": ${sig.confidence},
  "block":     ${sig.publishedAtBlock},
  "signature": "${sig.signature}"
}`}
            </pre>
          </div>

          <div className="sf-card sf-card-violet" style={{ padding: 20 }}>
            <div className="sf-eyebrow sf-eyebrow-violet">✦ OUTCOME</div>
            {stage >= 6 ? (
              <div style={{ marginTop: 12 }}>
                <div className="sf-mono" style={{ fontSize: 11, color: 'var(--sf-signal-win)' }}>VALIDATED · WIN</div>
                <div className="sf-display" style={{ fontSize: 36, color: 'var(--sf-signal-win)', marginTop: 8 }}>+218 bps</div>
                <div className="sf-mono sf-dim" style={{ fontSize: 10, marginTop: 6, lineHeight: 1.6 }}>
                  TWAP $3,481.40 · gas $1.84 · slippage 4 bps<br />
                  reputation +14 · attested to ERC-8004
                </div>
              </div>
            ) : (
              <div className="sf-dim sf-mono" style={{ marginTop: 12, fontSize: 11 }}>awaiting horizon · {fmtSeconds(sig.horizon)}</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function FlowStation({ step, idx, state, isLast, agent, agentCount }) {
  const dotColor = state === 'done' ? 'var(--sf-signal-win)' : state === 'active' ? 'var(--sf-gold-300)' : 'var(--sf-fg-ghost)';
  const ring = state === 'active' ? '0 0 0 4px rgba(212, 175, 55, 0.15), 0 0 24px rgba(212, 175, 55, 0.4)' : 'none';

  const details = [
    `scanning IdentityRegistry · ${agentCount || '?'} agents found · sorting by reputation…`,
    `HTTP 402 · sending ${agent.pricePerSignal} USDC via x402 facilitator…`,
    'verifying ed25519 signature · stamping 0G Compute attestation…',
    'checking position $1,200 ≤ max $5,000 · slippage 8 bps ≤ cap 25 bps · vol OK · liquidity OK',
    'POST /v1/quote → swap LONG WETH 0.347 · /v1/swap with Permit2 sig…',
    'cron tick · TWAP 3481.40 · pnl +218 bps · ReputationRegistry.attest(0x4e9f, true, 218)',
  ];
  const receipts = [
    `↳ matched: ${agent.ens} · rank #${agent.rank} · rep ${agent.reputation}`,
    `↳ tx 0xa42f…7b09 · ${agent.pricePerSignal} USDC · facilitator OK`,
    `↳ sig 0x8f4a…2b07 · published block 12,345,678`,
    '↳ risk attestation 0xc1ed…3a09 · all checks PASS',
    '↳ tx 0x91ec…44d2 · 0.347 WETH ↔ 1,201.42 USDC · gas 0.0008 ETH',
    `↳ attested · +218 bps · ${agent.name} reputation +14`,
  ];

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '40px 1fr', gap: 20, position: 'relative', paddingBottom: isLast ? 0 : 20 }}>
      {!isLast && (
        <div style={{ position: 'absolute', left: 19, top: 28, bottom: 0, width: 1, background: state === 'done' ? 'var(--sf-signal-win)' : 'var(--sf-border)', transition: 'background 0.4s' }} />
      )}
      <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 4 }}>
        <div style={{
          width: 24, height: 24, borderRadius: '50%',
          border: `1.5px solid ${dotColor}`,
          background: state === 'done' ? 'var(--sf-signal-win)' : state === 'active' ? 'rgba(212, 175, 55, 0.15)' : 'transparent',
          boxShadow: ring,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          transition: 'all 0.4s cubic-bezier(0.22, 1, 0.36, 1)',
        }}>
          {state === 'done' && <span style={{ color: 'var(--sf-void-100)', fontSize: 11, fontWeight: 700 }}>✓</span>}
          {state === 'active' && <span style={{ color: 'var(--sf-gold-300)', fontSize: 12, fontFamily: 'JetBrains Mono, monospace' }}>{String(idx + 1).padStart(2, '0')}</span>}
          {state === 'pending' && <span className="sf-mono sf-dim" style={{ fontSize: 10 }}>{String(idx + 1).padStart(2, '0')}</span>}
        </div>
      </div>
      <div style={{ paddingBottom: 4 }}>
        <div className="sf-display" style={{ fontSize: 18, color: state === 'pending' ? 'var(--sf-fg-mute)' : 'var(--sf-fg)' }}>
          {step.label}
        </div>
        <div className="sf-mono" style={{ fontSize: 11, color: state === 'pending' ? 'var(--sf-fg-ghost)' : 'var(--sf-fg-dim)', marginTop: 2, letterSpacing: '0.05em' }}>
          {step.desc}
        </div>
        {state === 'active' && (
          <div className="sf-mono" style={{ fontSize: 11, marginTop: 8, color: 'var(--sf-gold-300)' }}>{details[idx]}</div>
        )}
        {state === 'done' && (
          <div className="sf-mono" style={{ fontSize: 10.5, marginTop: 8, color: 'var(--sf-signal-win)', letterSpacing: '0.02em' }}>{receipts[idx]}</div>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// MAIN APP
// ─────────────────────────────────────────────────────────────────────
export default function SibylFiPrototype() {
  const [view, setView] = useState('leaderboard');
  const [selectedAgent, setSelectedAgent] = useState(null);
  const [agents, setAgents] = useState([]);
  const [signals, setSignals] = useState([]);

  useEffect(() => {
    const loadLeaderboard = () =>
      sibylfi.leaderboard()
        .then((entries) =>
          setAgents((prev) =>
            entries.map((e, i) => mapAgent(e, i + 1, prev.find((p) => p.id === e.ens_name)?.rank))
          )
        )
        .catch(() => {});
    const loadSignals = () =>
      sibylfi.signals()
        .then((rows) => setSignals(rows.map(mapSignal)))
        .catch(() => {});
    loadLeaderboard();
    loadSignals();
    const t = setInterval(() => { loadLeaderboard(); loadSignals(); }, 30000);
    return () => clearInterval(t);
  }, []);

  const goProfile = (id) => { setSelectedAgent(id); setView('profile'); };
  const goFlow = (id) => { setSelectedAgent(id); setView('flow'); };
  const goBack = () => setView('leaderboard');

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@400;500;600&family=Inter:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');

        :root {
          --sf-void-000: #050208;
          --sf-void-050: #0a0612;
          --sf-void-100: #100a1c;
          --sf-void-200: #1a0f2e;
          --sf-void-300: #251940;
          --sf-void-400: #322152;
          --sf-void-500: #4a3370;

          --sf-gold-100: #fff4c2;
          --sf-gold-300: #f0d875;
          --sf-gold-500: #d4af37;
          --sf-gold-700: #a8841f;

          --sf-violet-300: #c4a5ff;
          --sf-violet-500: #9b6dff;
          --sf-violet-600: #7c3aed;
          --sf-violet-700: #5b21b6;

          --sf-signal-win: #4ade80;
          --sf-signal-loss: #f87171;
          --sf-signal-pending: #fbbf24;

          --sf-bg: var(--sf-void-050);
          --sf-bg-deep: var(--sf-void-000);
          --sf-surface: rgba(26, 15, 46, 0.6);
          --sf-border: rgba(212, 175, 55, 0.12);
          --sf-border-strong: rgba(212, 175, 55, 0.35);
          --sf-border-violet: rgba(155, 109, 255, 0.25);

          --sf-fg: #f5e9d0;
          --sf-fg-dim: #b8a888;
          --sf-fg-mute: #786a52;
          --sf-fg-ghost: #4a4032;
        }

        .sf-root, .sf-root * { box-sizing: border-box; }
        .sf-root {
          font-family: 'Inter', system-ui, sans-serif;
          color: var(--sf-fg);
          background: var(--sf-bg-deep);
          min-height: 100vh;
          position: relative;
          -webkit-font-smoothing: antialiased;
        }
        .sf-root button { font: inherit; color: inherit; background: none; border: none; cursor: pointer; padding: 0; }

        /* Cosmos backdrop — animated star field */
        .sf-cosmos {
          position: fixed; inset: 0; z-index: 0; pointer-events: none; overflow: hidden;
          background:
            radial-gradient(ellipse 80% 50% at 50% -10%, rgba(124, 58, 237, 0.25), transparent 60%),
            radial-gradient(ellipse 60% 40% at 90% 100%, rgba(212, 175, 55, 0.12), transparent 60%),
            radial-gradient(ellipse 50% 30% at 10% 80%, rgba(155, 109, 255, 0.10), transparent 70%),
            var(--sf-bg-deep);
        }
        .sf-cosmos::before {
          content: ""; position: absolute; inset: 0;
          background-image:
            radial-gradient(1px 1px at 20% 30%, rgba(245, 233, 208, 0.6), transparent),
            radial-gradient(1px 1px at 60% 70%, rgba(245, 233, 208, 0.4), transparent),
            radial-gradient(1px 1px at 80% 20%, rgba(212, 175, 55, 0.7), transparent),
            radial-gradient(1px 1px at 35% 85%, rgba(245, 233, 208, 0.3), transparent),
            radial-gradient(1px 1px at 92% 55%, rgba(155, 109, 255, 0.6), transparent),
            radial-gradient(1px 1px at 45% 15%, rgba(245, 233, 208, 0.5), transparent),
            radial-gradient(1px 1px at 12% 60%, rgba(212, 175, 55, 0.5), transparent),
            radial-gradient(1px 1px at 75% 90%, rgba(245, 233, 208, 0.5), transparent),
            radial-gradient(1px 1px at 28% 45%, rgba(155, 109, 255, 0.4), transparent);
          background-size: 100% 100%;
          animation: sf-drift 120s linear infinite;
        }
        .sf-cosmos::after {
          content: ""; position: absolute; inset: 0;
          background:
            repeating-linear-gradient(0deg, transparent 0, transparent 80px, rgba(212, 175, 55, 0.02) 80px, rgba(212, 175, 55, 0.02) 81px),
            repeating-linear-gradient(90deg, transparent 0, transparent 80px, rgba(212, 175, 55, 0.02) 80px, rgba(212, 175, 55, 0.02) 81px);
          mask: radial-gradient(ellipse 70% 60% at 50% 50%, black, transparent);
          -webkit-mask: radial-gradient(ellipse 70% 60% at 50% 50%, black, transparent);
        }
        @keyframes sf-drift {
          0% { transform: translate3d(0, 0, 0); }
          100% { transform: translate3d(-40px, -20px, 0); }
        }

        /* Grain */
        .sf-grain {
          position: fixed; inset: 0; z-index: 1; pointer-events: none; opacity: 0.04; mix-blend-mode: overlay;
          background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='200' height='200'><filter id='n'><feTurbulence baseFrequency='0.9' numOctaves='2'/></filter><rect width='200' height='200' filter='url(%23n)' opacity='0.6'/></svg>");
        }

        /* App shell */
        .sf-app { position: relative; z-index: 2; min-height: 100vh; display: grid; grid-template-rows: auto 1fr; }

        /* Topbar */
        .sf-topbar {
          display: flex; align-items: center; gap: 16px;
          padding: 14px 28px; border-bottom: 1px solid var(--sf-border);
          background: linear-gradient(180deg, rgba(10, 6, 18, 0.8), rgba(10, 6, 18, 0.4));
          backdrop-filter: blur(12px);
          position: sticky; top: 0; z-index: 50;
          flex-wrap: wrap;
        }
        .sf-brand { display: flex; align-items: center; gap: 12px; }
        .sf-brand-name {
          font-family: 'Cinzel', serif; font-weight: 600; font-size: 20px;
          letter-spacing: 0.18em; color: var(--sf-gold-300); text-transform: uppercase;
        }
        .sf-brand-name em { font-style: normal; color: var(--sf-violet-300); }
        .sf-brand-sub {
          font-family: 'JetBrains Mono', monospace; font-size: 10px; color: var(--sf-fg-mute);
          letter-spacing: 0.2em; text-transform: uppercase;
        }
        .sf-nav { display: flex; gap: 16px; margin-left: 12px; }
        .sf-nav-item {
          padding: 8px 14px; font-family: 'JetBrains Mono', monospace; font-size: 11px;
          letter-spacing: 0.15em; text-transform: uppercase; color: var(--sf-fg-dim);
          border-radius: 2px; transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1); position: relative;
        }
        .sf-nav-item:hover { color: var(--sf-gold-300); }
        .sf-nav-item.is-active { color: var(--sf-gold-300); }
        .sf-nav-item.is-active::after {
          content: ""; position: absolute; left: 14px; right: 14px; bottom: 2px; height: 1px;
          background: linear-gradient(90deg, transparent, var(--sf-gold-500), transparent);
        }
        .sf-topbar-right { margin-left: auto; display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
        .sf-chip {
          position: relative;
          display: inline-flex; align-items: center; gap: 8px;
          padding: 8px 16px; border: 1px solid var(--sf-border); border-radius: 2px;
          font-family: 'JetBrains Mono', monospace; font-size: 10px; letter-spacing: 0.15em;
          text-transform: uppercase; color: var(--sf-fg-dim);
        }
        .sf-chip::before, .sf-chip::after {
          content: ""; position: absolute; width: 5px; height: 5px;
          border: 1px solid var(--sf-gold-500); pointer-events: none;
        }
        .sf-chip::before { top: -1px; left: -1px; border-right: none; border-bottom: none; }
        .sf-chip::after { bottom: -1px; right: -1px; border-left: none; border-top: none; }
        .sf-chip-dot {
          width: 6px; height: 6px; border-radius: 50%;
          background: var(--sf-signal-win); box-shadow: 0 0 8px var(--sf-signal-win);
          animation: sf-pulse 2s infinite;
        }
        @keyframes sf-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
        .sf-forge {
          position: relative;
          display: inline-flex; align-items: center; gap: 6px;
          margin-left: 4px;
          padding: 8px 14px; border-radius: 2px;
          border: 1px solid var(--sf-border-violet);
          background: linear-gradient(180deg, rgba(124, 58, 237, 0.10), rgba(124, 58, 237, 0.02));
          font-family: 'JetBrains Mono', monospace; font-size: 11px; letter-spacing: 0.2em;
          text-transform: uppercase; color: var(--sf-violet-300);
          transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
        }
        .sf-forge::before, .sf-forge::after {
          content: ""; position: absolute; width: 5px; height: 5px;
          border: 1px solid var(--sf-violet-500); pointer-events: none;
        }
        .sf-forge::before { top: -1px; left: -1px; border-right: none; border-bottom: none; }
        .sf-forge::after { bottom: -1px; right: -1px; border-left: none; border-top: none; }
        .sf-forge:hover {
          border-color: var(--sf-violet-500);
          background: rgba(124, 58, 237, 0.18);
          color: var(--sf-violet-300);
          box-shadow: 0 0 24px rgba(124, 58, 237, 0.25);
        }
        .sf-forge-plus { color: var(--sf-violet-500); font-weight: 500; }
        .sf-wallet {
          position: relative;
          display: inline-flex; align-items: center; gap: 10px;
          padding: 10px 18px; border: 1px solid var(--sf-gold-500); border-radius: 2px;
          background: linear-gradient(180deg, rgba(212, 175, 55, 0.18), rgba(212, 175, 55, 0.06));
          font-family: 'JetBrains Mono', monospace; font-size: 11px; font-weight: 500;
          letter-spacing: 0.18em; text-transform: uppercase; color: var(--sf-gold-100);
          transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
        }
        .sf-wallet::before, .sf-wallet::after {
          content: ""; position: absolute; width: 6px; height: 6px;
          border: 1px solid var(--sf-gold-500); pointer-events: none;
        }
        .sf-wallet::before { top: -1px; left: -1px; border-right: none; border-bottom: none; }
        .sf-wallet::after { bottom: -1px; right: -1px; border-left: none; border-top: none; }
        .sf-wallet:hover {
          background: linear-gradient(180deg, rgba(212, 175, 55, 0.28), rgba(212, 175, 55, 0.1));
          color: var(--sf-gold-100);
          box-shadow: 0 0 24px rgba(212, 175, 55, 0.25);
        }
        .sf-wallet-dot {
          display: inline-block; width: 6px; height: 6px; border-radius: 50%;
          background: var(--sf-gold-500); box-shadow: 0 0 8px rgba(212, 175, 55, 0.5);
        }
        .sf-wallet-chev {
          color: var(--sf-gold-300); font-size: 14px; line-height: 1;
          margin-left: 2px; transition: transform 0.2s;
        }
        .sf-wallet:hover .sf-wallet-chev { transform: translateX(2px); }
        .sf-wallet.is-connected {
          padding: 8px 14px;
          background: linear-gradient(180deg, rgba(212, 175, 55, 0.08), rgba(212, 175, 55, 0.02));
          border-color: var(--sf-border-strong);
          color: var(--sf-gold-300);
          font-weight: 400; letter-spacing: 0.04em; text-transform: none;
        }
        .sf-wallet.is-connected:hover {
          background: rgba(212, 175, 55, 0.12);
          border-color: var(--sf-gold-500);
          box-shadow: 0 0 16px rgba(212, 175, 55, 0.18);
        }
        .sf-wallet.is-connected .sf-wallet-dot {
          background: var(--sf-signal-win);
          box-shadow: 0 0 8px var(--sf-signal-win);
          animation: sf-pulse 2s infinite;
        }

        /* Layout */
        .sf-main { padding: 32px 28px 80px; max-width: 1600px; width: 100%; margin: 0 auto; }

        /* Type system */
        .sf-eyebrow {
          font-family: 'JetBrains Mono', monospace; font-size: 10px; letter-spacing: 0.22em;
          text-transform: uppercase; color: var(--sf-gold-500); margin-bottom: 8px;
        }
        .sf-eyebrow-violet { color: var(--sf-violet-300); }
        .sf-h1 {
          font-family: 'Cinzel', serif; font-weight: 500; font-size: clamp(32px, 5vw, 56px);
          line-height: 1.05; letter-spacing: -0.01em; color: var(--sf-fg); text-wrap: balance;
        }
        .sf-h1 em { font-style: normal; color: var(--sf-gold-300); }
        .sf-h2 { font-family: 'Cinzel', serif; font-weight: 500; font-size: 28px; letter-spacing: 0.02em; color: var(--sf-fg); }
        .sf-display { font-family: 'Cinzel', serif; font-weight: 500; }
        .sf-display-name {
          font-family: 'Cinzel', serif; font-weight: 500;
          text-transform: uppercase; letter-spacing: 0.06em;
        }
        .sf-lede {
          font-family: 'Inter', sans-serif; font-size: 16px; line-height: 1.6;
          color: var(--sf-fg-dim); max-width: 60ch;
        }
        .sf-mono { font-family: 'JetBrains Mono', monospace; }
        .sf-gold { color: var(--sf-gold-300); }
        .sf-violet { color: var(--sf-violet-300); }
        .sf-dim { color: var(--sf-fg-dim); }
        .sf-mute { color: var(--sf-fg-mute); }
        .sf-upper { text-transform: uppercase; letter-spacing: 0.15em; }

        /* Cards with gold corner brackets */
        .sf-card {
          background: linear-gradient(180deg, rgba(26, 15, 46, 0.7), rgba(16, 10, 28, 0.5));
          border: 1px solid var(--sf-border);
          border-radius: 4px;
          position: relative;
          backdrop-filter: blur(6px);
        }
        .sf-card-gold { border-color: var(--sf-border-strong); }
        .sf-card-violet { border-color: var(--sf-border-violet); }
        .sf-card::before, .sf-card::after {
          content: ""; position: absolute; width: 8px; height: 8px;
          border: 1px solid var(--sf-gold-500); pointer-events: none;
        }
        .sf-card::before { top: -1px; left: -1px; border-right: none; border-bottom: none; }
        .sf-card::after { bottom: -1px; right: -1px; border-left: none; border-top: none; }

        /* Buttons */
        .sf-btn {
          display: inline-flex; align-items: center; gap: 10px;
          padding: 12px 20px; font-family: 'JetBrains Mono', monospace; font-size: 11px;
          letter-spacing: 0.2em; text-transform: uppercase;
          border: 1px solid var(--sf-border-strong); color: var(--sf-gold-300);
          border-radius: 2px; transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
          background: linear-gradient(180deg, rgba(212, 175, 55, 0.06), transparent);
        }
        .sf-btn:hover {
          border-color: var(--sf-gold-500);
          background: linear-gradient(180deg, rgba(212, 175, 55, 0.18), rgba(212, 175, 55, 0.04));
          color: var(--sf-gold-100); box-shadow: 0 0 24px rgba(212, 175, 55, 0.2);
        }
        .sf-btn-primary {
          background: linear-gradient(180deg, var(--sf-gold-500), var(--sf-gold-700));
          color: var(--sf-void-100); border-color: var(--sf-gold-500);
        }
        .sf-btn-primary:hover {
          background: linear-gradient(180deg, var(--sf-gold-300), var(--sf-gold-500));
          color: var(--sf-void-000); box-shadow: 0 0 32px rgba(212, 175, 55, 0.4);
        }
        .sf-btn-violet { border-color: var(--sf-border-violet); color: var(--sf-violet-300); }
        .sf-btn-violet:hover {
          border-color: var(--sf-violet-500);
          background: rgba(124, 58, 237, 0.15);
          color: var(--sf-violet-300);
          box-shadow: 0 0 24px rgba(124, 58, 237, 0.3);
        }
        .sf-btn-ghost { border-color: var(--sf-border); color: var(--sf-fg-dim); background: transparent; }
        .sf-btn-ghost:hover {
          border-color: var(--sf-fg-dim); color: var(--sf-fg);
          background: var(--sf-surface); box-shadow: none;
        }
        .sf-btn-sm { padding: 8px 14px; font-size: 10px; }

        /* Stats */
        .sf-stat-label {
          font-family: 'JetBrains Mono', monospace; font-size: 10px; letter-spacing: 0.2em;
          text-transform: uppercase; color: var(--sf-fg-mute); margin-bottom: 4px;
        }

        /* Tags */
        .sf-tag {
          display: inline-flex; align-items: center; gap: 6px;
          padding: 4px 10px; font-family: 'JetBrains Mono', monospace; font-size: 10px;
          letter-spacing: 0.15em; text-transform: uppercase;
          border: 1px solid var(--sf-border); color: var(--sf-fg-dim); border-radius: 2px;
        }
        .sf-tag--win { border-color: rgba(74, 222, 128, 0.4); color: var(--sf-signal-win); background: rgba(74, 222, 128, 0.06); }
        .sf-tag--loss { border-color: rgba(248, 113, 113, 0.4); color: var(--sf-signal-loss); background: rgba(248, 113, 113, 0.06); }
        .sf-tag--pending { border-color: rgba(251, 191, 36, 0.4); color: var(--sf-signal-pending); background: rgba(251, 191, 36, 0.06); }
        .sf-tag--violet { border-color: var(--sf-border-violet); color: var(--sf-violet-300); background: rgba(124, 58, 237, 0.08); }
        .sf-tag--gold { border-color: var(--sf-border-strong); color: var(--sf-gold-300); background: rgba(212, 175, 55, 0.06); }

        /* Oracle quote */
        .sf-oracle-quote {
          font-family: 'Cinzel', serif; font-weight: 400;
          font-size: 17px; line-height: 1.55; color: var(--sf-violet-300);
          border-left: 1px solid var(--sf-violet-500); padding: 6px 0 6px 20px;
          letter-spacing: 0.02em;
          position: relative;
        }
        .sf-oracle-quote::before {
          content: "❝"; position: absolute; left: -10px; top: -14px;
          font-size: 32px; color: var(--sf-gold-500);
          background: var(--sf-bg-deep); padding: 0 4px; line-height: 1;
        }

        /* Live dot */
        .sf-live-dot {
          display: inline-block; width: 6px; height: 6px; border-radius: 50%;
          background: var(--sf-signal-win); margin-right: 6px;
          box-shadow: 0 0 8px var(--sf-signal-win); animation: sf-pulse 1.5s infinite;
        }

        /* Number flip */
        .sf-num-flip { display: inline-block; transition: color 0.4s, transform 0.4s cubic-bezier(0.22, 1, 0.36, 1); }
        .sf-flash-up { color: var(--sf-signal-win); transform: translateY(-2px); }
        .sf-flash-down { color: var(--sf-signal-loss); transform: translateY(2px); }

        /* Leaderboard row reorder pulse */
        .sf-lb-row:hover { background: rgba(212, 175, 55, 0.04) !important; }
        .sf-lb-row-up { background: linear-gradient(90deg, rgba(74, 222, 128, 0.06), transparent); }
        .sf-lb-row-down { background: linear-gradient(90deg, rgba(248, 113, 113, 0.04), transparent); }

        @keyframes sf-rune-spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

        /* Scrollbar */
        .sf-root ::-webkit-scrollbar { width: 8px; height: 8px; }
        .sf-root ::-webkit-scrollbar-track { background: var(--sf-void-100); }
        .sf-root ::-webkit-scrollbar-thumb { background: var(--sf-void-400); border-radius: 4px; }
        .sf-root ::-webkit-scrollbar-thumb:hover { background: var(--sf-violet-700); }
      `}</style>

      <div className="sf-root">
        <div className="sf-cosmos" />
        <div className="sf-grain" />
        <div className="sf-app">
          <Topbar
            view={view}
            setView={(v) => { setView(v); setSelectedAgent(null); }}
          />
          <main className="sf-main">
            {view === 'leaderboard' && <Leaderboard agents={agents} onAgentSelect={goProfile} />}
            {view === 'profile' && <AgentProfile agentId={selectedAgent} agents={agents} signals={signals} onBack={goBack} onBuy={goFlow} />}
            {view === 'flow' && <SignalFlow onBack={goBack} agentId={selectedAgent} agents={agents} />}
            {view === 'feed' && <SignalFeed agents={agents} signals={signals} onAgentSelect={goProfile} onBuy={goFlow} />}
          </main>
        </div>
      </div>
    </>
  );
}
