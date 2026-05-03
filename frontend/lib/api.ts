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

// ── Multi-tenant Research Agent registry (v2) ──────────────────────────

export type Profile = 'swing' | 'scalper';
export type Appetite = 'conservative' | 'balanced' | 'aggressive';

export interface AgentRecord {
  id: number;
  ens_name: string;
  display_name: string;
  profile: Profile;
  appetite: Appetite;
  token: string;
  price_per_signal_usdc: number;
  address: string;
  params: Record<string, unknown>;
  created_at: string;
}

export interface CreateAgentRequest {
  display_name: string;
  ens_name: string;
  profile: Profile;
  token?: string;
  appetite?: Appetite;
  price_per_signal_usdc?: number;
  params?: Record<string, unknown>;
}

export interface PublishResponse {
  status: 'published' | 'no_signal';
  reason?: string | null;
  signal?: Record<string, unknown> | null;
}

export interface StrategyPreviewRow {
  publisher_ens: string;
  profile: 'swing' | 'scalper';
  token: string;
  accept: boolean;
  setup?: string | null;
  reason?: string | null;
}

export interface StrategyPreview {
  fetched_at: string;
  rows: StrategyPreviewRow[];
}

async function del<T>(path: string): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, { method: 'DELETE' });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

export const sibylfi = {
  leaderboard: () => get<LeaderboardEntry[]>('/leaderboard'),
  signals: (status?: 'live' | 'settled' | 'expired') =>
    get<SignalRow[]>(`/signals${status ? `?status=${status}` : ''}`),
  agentDetail: (ensName: string) => get<unknown>(`/agent/${encodeURIComponent(ensName)}`),
  strategyPreview: () => get<StrategyPreview>('/strategy-preview'),
  health: () => get<{ status: string }>('/health'),

  // Multi-tenant agent registry
  listAgents: () => get<AgentRecord[]>('/agents'),
  createAgent: (req: CreateAgentRequest) => post<AgentRecord>('/api/agents', req),
  deleteAgent: (id: number) => del<{ deleted: number }>(`/agents/${id}`),
  defaultParams: (profile: Profile) =>
    get<{ profile: Profile; params: Record<string, number | string> }>(`/agents/_defaults/${profile}`),
  publishCustomSignal: (id: number, token = 'WETH/USDC') =>
    post<PublishResponse>(`/api/agents/${id}/publish-signal?token=${encodeURIComponent(token)}`),

  // Demo controls
  publishSignal: (persona: string, token = 'WETH/USDC') =>
    post<unknown>(`/demo/publish-signal?persona=${persona}&token=${encodeURIComponent(token)}`),
  settleNow: () => post<{ settled: number }>('/demo/settle-now'),
  tradeNow: (token = 'WETH/USDC', capitalUsd = 1000, publisherEns?: string) => {
    const params = new URLSearchParams({ token, capital_usd: String(capitalUsd) });
    if (publisherEns) params.set('publisher_ens', publisherEns);
    return post<unknown>(`/demo/trade-now?${params.toString()}`);
  },
};
