"use client";

import { Badge } from "@/components/ui/badge";
import type { ServerStatus } from "@/lib/market-types";

function pct(subscribed: number, limit: number): string {
  if (!limit) return "0%";
  return `${((subscribed / limit) * 100).toFixed(1)}%`;
}

export function ConnectionStatus({ status }: { status: ServerStatus }) {
  return (
    <div className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
      <Badge variant={status.connected ? "default" : "secondary"}>
        <span
          className={`mr-1.5 inline-block size-2 rounded-full ${
            status.connected ? "bg-emerald-500" : "bg-amber-500"
          }`}
        />
        {status.connected ? "Connected" : "Disconnected"}
      </Badge>
      <span className="tabular-nums">
        {status.subscribed.toLocaleString()} / {status.limit.toLocaleString()} keys
      </span>
      <span className="tabular-nums">{pct(status.subscribed, status.limit)}</span>
    </div>
  );
}
