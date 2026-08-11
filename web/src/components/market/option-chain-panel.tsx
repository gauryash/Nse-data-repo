"use client";

import { useEffect, useState } from "react";
import { XIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import type { Chain, ServerStatus } from "@/lib/market-types";

import { OptionChainTable, OptionMoversTable } from "@/components/market/option-chain-table";

interface Props {
  chain: Chain;
  status: ServerStatus;
  onExpiryChange: (symbol: string, expiry: string) => void;
  onClose: (id: string) => void;
}

export function OptionChainPanel({ chain, status, onExpiryChange, onClose }: Props) {
  const [expiries, setExpiries] = useState<string[]>([]);

  useEffect(() => {
    let cancelled = false;
    api
      .expiries(chain.underlying_symbol)
      .then((list) => !cancelled && setExpiries(list))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [chain.underlying_symbol]);

  return (
    <Card className="min-w-[420px]">
      <CardHeader className="flex-row items-center justify-between space-y-0 pb-3">
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
            {chain.underlying_symbol}
            {status.connected ? (
              <Badge variant="default" className="gap-1 text-[10px]">
                <span className="inline-block size-1.5 rounded-full bg-emerald-400" />
                LIVE
              </Badge>
            ) : (
              <Badge variant="outline" className="text-[10px]">
                OFFLINE
              </Badge>
            )}
          </CardTitle>
          <CardDescription>{chain.underlying_name}</CardDescription>
        </div>
        <div className="flex items-center gap-2">
          {expiries.length ? (
            <Select value={chain.expiry} onValueChange={(v) => onExpiryChange(chain.underlying_symbol, v)}>
              <SelectTrigger className="h-8 w-32">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {expiries.map((e) => (
                  <SelectItem key={e} value={e}>
                    {e}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (
            <Skeleton className="h-8 w-32" />
          )}
          <Button variant="ghost" size="icon" onClick={() => onClose(chain.id)} aria-label="Close chain">
            <XIcon className="size-4" />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        <Tabs defaultValue="chain">
          <TabsList className="mb-2">
            <TabsTrigger value="chain">Option Chain</TabsTrigger>
            <TabsTrigger value="movers">% Movers</TabsTrigger>
          </TabsList>
          <TabsContent value="chain">
            <OptionChainTable chain={chain} />
          </TabsContent>
          <TabsContent value="movers">
            <OptionMoversTable chain={chain} />
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}
