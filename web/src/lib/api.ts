import type { AssetGroup, Contract, ServerStatus, Underlying, Universe } from "@/lib/market-types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

export function wsUrl(): string {
  return API_BASE.replace(/^http/, "ws") + "/ws";
}

export async function fetchJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}: ${path}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  status: () => fetchJSON<ServerStatus>("/api/status"),
  universes: () => fetchJSON<Universe[]>("/api/universes"),
  underlyings: (group: AssetGroup) => fetchJSON<Underlying[]>(`/api/underlyings/${group}`),
  expiries: (symbol: string) => fetchJSON<string[]>(`/api/expiries/${encodeURIComponent(symbol)}`),
  chain: (symbol: string, expiry: string) =>
    fetchJSON<{ underlying_symbol: string; expiry: string; contracts: Contract[] }>(
      `/api/chain/${encodeURIComponent(symbol)}?expiry=${expiry}`
    ),
};
