"use client";

import { api, wsUrl } from "@/lib/api";
import type { Chain, Contract, ServerStatus, Snapshot, Tick } from "@/lib/market-types";

type Listener = () => void;

const EMPTY_STATUS: ServerStatus = {
  connected: false,
  subscribed: 0,
  limit: 5000,
  chains: {},
};

/**
 * MarketClient — singleton WebSocket client + in-memory quote store.
 *
 * - one WS connection to the Python backend (`/ws`)
 * - watch/unwatch option chains by id (`<symbol>:<expiry>`)
 * - merges batched tick updates into a per-chain quote map
 * - auto-reconnects and re-watches active chains
 * - exposes a referentially-stable snapshot for useSyncExternalStore
 */
class MarketClient {
  private ws: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectDelay = 1000;

  private status: ServerStatus = EMPTY_STATUS;
  private chains = new Map<string, Chain>();
  private pending = new Map<string, { symbol: string; expiry: string }>();
  private listeners = new Set<Listener>();
  private snapshot: Snapshot = { status: EMPTY_STATUS, chains: [] };

  // ------------------------------------------------------------------
  // lifecycle
  // ------------------------------------------------------------------

  connect(): void {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }
    const ws = new WebSocket(wsUrl());
    this.ws = ws;
    ws.onopen = () => {
      this.reconnectDelay = 1000;
      this.setStatus({ ...this.status, connected: true });
      for (const [id, c] of this.pending) this.sendWatch(id, c.symbol, c.expiry);
    };
    ws.onmessage = (ev) => this.handleMessage(ev.data);
    ws.onclose = () => {
      this.setStatus({ ...this.status, connected: false });
      this.scheduleReconnect();
    };
    ws.onerror = () => ws.close();
  }

  disconnect(): void {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
    this.ws = null;
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, this.reconnectDelay);
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, 15000);
  }

  // ------------------------------------------------------------------
  // watch API
  // ------------------------------------------------------------------

  async watch(id: string, symbol: string, expiry: string): Promise<void> {
    this.pending.set(id, { symbol, expiry });
    this.sendWatch(id, symbol, expiry);
    if (this.chains.has(id)) return;
    try {
      const chain = await api.chain(symbol, expiry);
      const contracts: Contract[] = chain.contracts;
      const quotes: Record<string, Tick> = {};
      for (const c of contracts) {
        const tick = this.lastTicks.get(c.instrument_key);
        if (tick) quotes[c.instrument_key] = tick;
      }
      this.chains.set(id, {
        id,
        underlying_symbol: symbol,
        underlying_name: contracts[0]?.underlying_name ?? symbol,
        expiry,
        contracts,
        quotes,
      });
      this.notify();
    } catch {
      // backend unreachable; the WS 'watched' flow will still drive ticks
    }
  }

  unwatch(id: string): void {
    this.pending.delete(id);
    this.chains.delete(id);
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ op: "unwatch", id }));
    }
    this.notify();
  }

  unwatchAll(): void {
    for (const id of [...this.chains.keys()]) this.unwatch(id);
  }

  private sendWatch(id: string, symbol: string, expiry: string): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ op: "watch", id, underlying_symbol: symbol, expiry }));
    }
  }

  // ------------------------------------------------------------------
  // incoming messages
  // ------------------------------------------------------------------

  private handleMessage(data: unknown): void {
    let msg: Record<string, unknown>;
    try {
      msg = JSON.parse(String(data));
    } catch {
      return;
    }
    switch (msg.type) {
      case "status":
        this.setStatus(msg as unknown as ServerStatus);
        break;
      case "watched": {
        const id = String(msg.id);
        const snapshot = (msg.snapshot ?? {}) as Record<string, Tick>;
        for (const [key, tick] of Object.entries(snapshot)) this.lastTicks.set(key, tick);
        const chain = this.chains.get(id);
        if (chain) {
          chain.quotes = { ...chain.quotes, ...snapshot };
          this.notify();
        }
        break;
      }
      case "ticks": {
        const ticks = (msg.ticks ?? []) as Tick[];
        for (const tick of ticks) {
          this.lastTicks.set(tick.instrument_key, tick);
          for (const chain of this.chains.values()) {
            if (chain.contracts.some((c) => c.instrument_key === tick.instrument_key)) {
              chain.quotes = { ...chain.quotes, [tick.instrument_key]: tick };
            }
          }
        }
        this.notify();
        break;
      }
    }
  }

  // ------------------------------------------------------------------
  // store plumbing
  // ------------------------------------------------------------------

  /** Latest tick per instrument key (shared across chains). */
  private lastTicks = new Map<string, Tick>();

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  getSnapshot(): Snapshot {
    return this.snapshot;
  }

  private setStatus(status: ServerStatus): void {
    this.status = status;
    this.rebuild();
  }

  private notify(): void {
    this.rebuild();
    for (const l of this.listeners) l();
  }

  private rebuild(): void {
    this.snapshot = {
      status: this.status,
      chains: [...this.chains.values()].sort((a, b) => a.underlying_symbol.localeCompare(b.underlying_symbol)),
    };
  }
}

export const market = new MarketClient();
