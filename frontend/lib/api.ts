/**
 * Thin client for the SibylFi orchestrator.
 * Frontend uses Next.js rewrites to proxy /api/* to the orchestrator URL.
 */

export interface LeaderboardEntry {
  agent_id: number;
  ens_name: string;
  address: string;
  endpoint: string;
  reputation_score: number;
  total_attestations: number;
  wins: number;
  losses: number;
  win_rate: number;
  roi_7d_bps: number;
  capital_served_usd: number;
  cold_start: boolean;
}

export interface SignalRow {
  signal_id: string;
  publisher: string;
  token: string;
  direction: 'long' | 'short';
  reference_price: number;
  target_price: number;
  stop_price: number;
  horizon_seconds: number;
  confidence_bps: number;
  published_at: string;
  horizon_expires_at: string;
  settled: boolean;
  outcome?: 'win' | 'loss' | 'expired';
  pnl_bps_net?: number;
  capital_deployed_usd?: number;
}

const API_BASE = '/api';

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, { cache: 'no-store' });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method: 'POST',
    headers: body ? { 'content-type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

export const sibylfi = {
  leaderboard: () => get<LeaderboardEntry[]>('/leaderboard'),
  signals: (status?: 'live' | 'settled' | 'expired') =>
    get<SignalRow[]>(`/signals${status ? `?status=${status}` : ''}`),
  agentDetail: (ensName: string) => get<unknown>(`/agent/${encodeURIComponent(ensName)}`),
  health: () => get<{ status: string }>('/health'),

  // Demo controls
  publishSignal: (persona: string, token = 'WETH/USDC') =>
    post<unknown>(`/demo/publish-signal?persona=${persona}&token=${encodeURIComponent(token)}`),
  settleNow: () => post<{ settled: number }>('/demo/settle-now'),
  tradeNow: (token = 'WETH/USDC', capitalUsd = 1000) =>
    post<unknown>(`/demo/trade-now?token=${encodeURIComponent(token)}&capital_usd=${capitalUsd}`),
};
