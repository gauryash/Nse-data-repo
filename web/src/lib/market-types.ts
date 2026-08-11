export type AssetGroup = "indices" | "stocks" | "commodities";

export interface ServerStatus {
  connected: boolean;
  subscribed: number;
  limit: number;
  chains: Record<string, string>;
}

export interface Underlying {
  symbol: string;
  name: string;
  expiries: number;
}

export interface Universe {
  name: string;
  total: number;
  eligible: number;
  symbols: string[];
}

export interface Contract {
  instrument_key: string;
  tradingsymbol: string;
  underlying_symbol: string;
  underlying_name: string;
  underlying_type: string;
  option_type: "CE" | "PE";
  expiry: string | null;
  strike: number | null;
  lot_size: number;
  tick_size: number;
}

export interface Tick {
  instrument_key: string;
  ltp: number | null;
  cp: number | null;
  pct_change: number | null;
  timestamp: number | null;
}

export interface Chain {
  id: string;
  underlying_symbol: string;
  underlying_name: string;
  expiry: string;
  contracts: Contract[];
  quotes: Record<string, Tick>;
}

export interface Snapshot {
  status: ServerStatus;
  chains: Chain[];
}
