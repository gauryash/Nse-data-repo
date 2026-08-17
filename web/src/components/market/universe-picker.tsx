"use client";

import { useEffect, useMemo, useState } from "react";

import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { api } from "@/lib/api";
import type { AssetGroup, Underlying, Universe } from "@/lib/market-types";

interface GroupSection {
  key: string;
  title: string;
  subtitle?: string;
  items: { symbol: string; name: string; hasOptions: boolean }[];
}

interface Props {
  selected: Set<string>;
  onToggle: (symbol: string, name: string, group: AssetGroup) => void;
}

export function UniversePicker({ selected, onToggle }: Props) {
  const [query, setQuery] = useState("");
  const [universes, setUniverses] = useState<Universe[]>([]);
  const [groups, setGroups] = useState<Record<AssetGroup, Underlying[]>>({
    indices: [],
    stocks: [],
    commodities: [],
  });

  useEffect(() => {
    let cancelled = false;
    api
      .universes()
      .then((u) => !cancelled && setUniverses(u))
      .catch(() => {});
    (["indices", "stocks", "commodities"] as AssetGroup[]).forEach((g) => {
      api
        .underlyings(g)
        .then((items) => !cancelled && setGroups((prev) => ({ ...prev, [g]: items })))
        .catch(() => {});
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const sections = useMemo<GroupSection[]>(() => {
    const out: GroupSection[] = [];
    for (const u of universes) {
      const items = u.symbols
        .filter((s) => s.toLowerCase().includes(query.toLowerCase()))
        .map((s) => ({ symbol: s, name: s, hasOptions: true }));
      if (items.length) {
        out.push({
          key: u.name,
          title: u.name.toUpperCase(),
          subtitle: `${u.eligible}/${u.total} with F&O`,
          items,
        });
      }
    }
    const groupMeta: { group: AssetGroup; title: string }[] = [
      { group: "indices", title: "Indices" },
      { group: "stocks", title: "NSE F&O Stocks" },
      { group: "commodities", title: "Commodities" },
    ];
    for (const { group, title } of groupMeta) {
      const items = groups[group]
        .filter((u) => u.symbol.toLowerCase().includes(query.toLowerCase()))
        .map((u) => ({ symbol: u.symbol, name: u.name, hasOptions: true }));
      if (items.length) {
        out.push({ key: group, title, items });
      }
    }
    return out;
  }, [universes, groups, query]);

  return (
    <div className="flex h-full flex-col gap-3">
      <Input
        placeholder="Search underlyings…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      <ScrollArea className="flex-1">
        <div className="space-y-4 pr-2">
          {sections.map((section) => (
            <div key={section.key}>
              <div className="flex items-baseline justify-between">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {section.title}
                </h3>
                {section.subtitle ? (
                  <span className="text-[11px] text-muted-foreground/70">{section.subtitle}</span>
                ) : null}
              </div>
              <div className="mt-1.5 grid grid-cols-1 gap-x-3 gap-y-1">
                {section.items.map((item) => (
                  <label
                    key={item.symbol}
                    className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-sm hover:bg-muted/60"
                  >
                    <Checkbox
                      checked={selected.has(item.symbol)}
                      onCheckedChange={() => onToggle(item.symbol, item.name, section.key as AssetGroup)}
                    />
                    <span className="font-medium">{item.symbol}</span>
                    {item.name !== item.symbol ? (
                      <span className="truncate text-xs text-muted-foreground">{item.name}</span>
                    ) : null}
                  </label>
                ))}
              </div>
              <Separator className="mt-3" />
            </div>
          ))}
          {!sections.length ? (
            <p className="text-sm text-muted-foreground">No matches.</p>
          ) : null}
        </div>
      </ScrollArea>
    </div>
  );
}
