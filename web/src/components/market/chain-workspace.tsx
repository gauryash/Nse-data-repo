"use client";

import { ConnectionStatus } from "@/components/market/connection-status";
import { OptionChainPanel } from "@/components/market/option-chain-panel";
import { UniversePicker } from "@/components/market/universe-picker";
import { market } from "@/lib/market-store";
import type { Snapshot } from "@/lib/market-types";

interface Props {
  snapshot: Snapshot;
}

export function ChainWorkspace({ snapshot }: Props) {
  const selected = new Set(snapshot.chains.map((c) => c.underlying_symbol));

  async function toggle(symbol: string) {
    if (selected.has(symbol)) {
      for (const chain of snapshot.chains) {
        if (chain.underlying_symbol === symbol) {
          market.unwatch(chain.id);
        }
      }
      return;
    }
    try {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000"}/api/expiries/${encodeURIComponent(symbol)}`
      );
      if (!res.ok) return;
      const expiries: string[] = await res.json();
      if (!expiries.length) return;
      market.watch(`${symbol}:${expiries[0]}`, symbol, expiries[0]);
    } catch {
      // backend unreachable — ignore
    }
  }

  function changeExpiry(symbol: string, expiry: string) {
    for (const chain of snapshot.chains) {
      if (chain.underlying_symbol === symbol) market.unwatch(chain.id);
    }
    market.watch(`${symbol}:${expiry}`, symbol, expiry);
  }

  function close(id: string) {
    market.unwatch(id);
  }

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col gap-3">
      <div className="flex items-center justify-between border-b pb-2">
        <h2 className="text-lg font-semibold">Options Monitor</h2>
        <ConnectionStatus status={snapshot.status} />
      </div>
      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[280px_1fr]">
        <aside className="min-h-0 rounded-lg border bg-card p-3">
          <UniversePicker selected={selected} onToggle={toggle} />
        </aside>
        <main className="grid min-h-0 auto-rows-max gap-4 overflow-y-auto xl:grid-cols-2">
          {snapshot.chains.map((chain) => (
            <OptionChainPanel
              key={chain.id}
              chain={chain}
              status={snapshot.status}
              onExpiryChange={changeExpiry}
              onClose={close}
            />
          ))}
          {!snapshot.chains.length ? (
            <div className="col-span-full flex h-64 items-center justify-center rounded-lg border border-dashed text-sm text-muted-foreground">
              Select underlyings from the left panel to open live option chains.
            </div>
          ) : null}
        </main>
      </div>
    </div>
  );
}
