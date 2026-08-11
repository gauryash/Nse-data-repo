"use client";

import { useMemo, useRef } from "react";

import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Chain, Tick } from "@/lib/market-types";

function fmtPct(v: number | null): string {
  if (v === null || Number.isNaN(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
}

function pctClass(v: number | null): string {
  if (v === null || Number.isNaN(v) || v === 0) return "text-muted-foreground";
  return v > 0 ? "text-emerald-600 dark:text-emerald-500" : "text-red-600 dark:text-red-500";
}

function fmtPrice(v: number | null): string {
  if (v === null || Number.isNaN(v)) return "—";
  return v.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

export function OptionChainTable({ chain }: { chain: Chain }) {
  const rows = useMemo(() => {
    const byStrike = new Map<number, { ce?: Tick; pe?: Tick }>();
    for (const c of chain.contracts) {
      if (c.strike === null) continue;
      const entry = byStrike.get(c.strike) ?? {};
      const tick = chain.quotes[c.instrument_key];
      if (c.option_type === "CE") entry.ce = tick;
      else entry.pe = tick;
      byStrike.set(c.strike, entry);
    }
    return [...byStrike.entries()]
      .sort((a, b) => a[0] - b[0])
      .map(([strike, pair]) => ({ strike, ...pair }));
  }, [chain]);

  return (
    <ScrollArea className="h-[420px]">
      <Table>
        <TableHeader className="sticky top-0 bg-background">
          <TableRow>
            <TableHead className="w-[22%] text-right">CE %</TableHead>
            <TableHead className="w-[22%] text-right">CE LTP</TableHead>
            <TableHead className="w-[12%] text-center">Strike</TableHead>
            <TableHead className="w-[22%] text-left">PE LTP</TableHead>
            <TableHead className="w-[22%] text-left">PE %</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.strike} className="tabular-nums">
              <TableCell className={`text-right ${pctClass(row.ce?.pct_change ?? null)}`}>
                {fmtPct(row.ce?.pct_change ?? null)}
              </TableCell>
              <TableCell className="text-right">{fmtPrice(row.ce?.ltp ?? null)}</TableCell>
              <TableCell className="text-center font-semibold">
                {row.strike.toLocaleString("en-IN")}
              </TableCell>
              <TableCell>{fmtPrice(row.pe?.ltp ?? null)}</TableCell>
              <TableCell className={pctClass(row.pe?.pct_change ?? null)}>
                {fmtPct(row.pe?.pct_change ?? null)}
              </TableCell>
            </TableRow>
          ))}
          {!rows.length ? (
            <TableRow>
              <TableCell colSpan={5} className="text-center text-muted-foreground">
                No contracts.
              </TableCell>
            </TableRow>
          ) : null}
        </TableBody>
      </Table>
    </ScrollArea>
  );
}

export function OptionMoversTable({ chain }: { chain: Chain }) {
  const rows = useMemo(() => {
    const out: { contract: (typeof chain.contracts)[number]; tick: Tick }[] = [];
    for (const c of chain.contracts) {
      const tick = chain.quotes[c.instrument_key];
      if (tick?.pct_change !== null && tick?.pct_change !== undefined && !Number.isNaN(tick.pct_change)) {
        out.push({ contract: c, tick });
      }
    }
    return out.sort((a, b) => b.tick.pct_change! - a.tick.pct_change!);
  }, [chain]);

  const parentRef = useRef<HTMLDivElement>(null);

  return (
    <ScrollArea ref={parentRef} className="h-[420px]">
      <Table>
        <TableHeader className="sticky top-0 bg-background">
          <TableRow>
            <TableHead>Contract</TableHead>
            <TableHead className="text-right">Strike</TableHead>
            <TableHead className="text-right">LTP</TableHead>
            <TableHead className="text-right">Change</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map(({ contract, tick }) => (
            <TableRow key={contract.instrument_key} className="tabular-nums">
              <TableCell className="font-mono text-xs">{contract.tradingsymbol}</TableCell>
              <TableCell className="text-right">{fmtPrice(contract.strike)}</TableCell>
              <TableCell className="text-right">{fmtPrice(tick.ltp)}</TableCell>
              <TableCell className={`text-right ${pctClass(tick.pct_change)}`}>
                {fmtPct(tick.pct_change)}
              </TableCell>
            </TableRow>
          ))}
          {!rows.length ? (
            <TableRow>
              <TableCell colSpan={4} className="text-center text-muted-foreground">
                Waiting for ticks…
              </TableCell>
            </TableRow>
          ) : null}
        </TableBody>
      </Table>
    </ScrollArea>
  );
}
