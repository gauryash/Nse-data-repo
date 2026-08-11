"use client";

import { useEffect, useSyncExternalStore } from "react";

import { market } from "@/lib/market-store";
import type { Snapshot } from "@/lib/market-types";

/** Subscribe the component tree to the singleton market store. */
export function useMarketFeed(): Snapshot {
  const snapshot = useSyncExternalStore(
    market.subscribe.bind(market),
    market.getSnapshot.bind(market),
    market.getSnapshot.bind(market)
  );

  useEffect(() => {
    market.connect();
    return () => market.disconnect();
  }, []);

  return snapshot;
}
