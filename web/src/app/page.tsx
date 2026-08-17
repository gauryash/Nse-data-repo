"use client";

import { ChainWorkspace } from "@/components/market/chain-workspace";
import { useMarketFeed } from "@/hooks/use-market-feed";

export default function Home() {
  const snapshot = useMarketFeed();

  return (
    <div className="flex flex-1 flex-col bg-zinc-50 p-4 font-sans dark:bg-black">
      <header className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">Options Monitor</h1>
          <p className="text-sm text-muted-foreground">
            Upstox Market Data Feed V3 · LTPC
          </p>
        </div>
      </header>
      <ChainWorkspace snapshot={snapshot} />
    </div>
  );
}
