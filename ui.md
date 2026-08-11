Yes. Based on the current Upstox docs and the architecture in your README, I would add a **live-market layer** beside your historical pipeline rather than mixing WebSocket logic into `UpstoxOptionsProvider`. Your current project already has good seams around instrument discovery/storage, so this can fit cleanly. 

### 1. The architecture I recommend

```text
                         UPSTOX ONLY
                  ┌─────────────────────────┐
                  │ Upstox BOD Instruments │
                  │ Upstox REST APIs       │
                  │ Market Data Feed V3 WS │
                  └────────────┬────────────┘
                               │
                    Python backend
                               │
              ┌────────────────▼───────────────┐
              │       LiveMarketHub            │
              │                                │
              │ - one Upstox WS connection    │
              │ - subscribe / unsubscribe     │
              │ - reference-count keys        │
              │ - reconnect + resubscribe     │
              │ - calculate % change          │
              │ - enforce subscription limit  │
              └─────────┬─────────────┬────────┘
                        │             │
                 Option catalog   Quote store
                        │             │
                        └──────┬──────┘
                               │
                       Your local WS
                               │
                       Next.js + shadcn
                               │
           ┌───────────────────┼───────────────────┐
           │                   │                   │
      NIFTY Chain       RELIANCE Chain       CRUDEOIL Chain
           │                   │                   │
       live rows            live rows            live rows
```

**Do not create an Upstox connection for every option-chain card.** Your shadcn cards should all use one central `LiveMarketHub`.

Upstox Market Data Feed V3 currently allows **5,000 keys when using LTPC alone**, 3,000 for option-greeks alone, and 2,000 for full mode on a normal connection; it also limits normal accounts to two connections. V3 supports dynamic `sub`, `unsub`, and `change_mode`. ([upstox.com][1])

For your requirement—live price plus percentage change—**LTPC is the correct default mode**. You get `ltp` and `cp`, which is enough to calculate:

```python
pct_change = ((ltp - cp) / cp) * 100 if cp else None
```

The official Upstox SDK describes `cp` in LTPC as the previous closing price. ([GitHub][2])

---

## 2. First change: stop using the deprecated instrument CSV

You currently have:

```python
upstox_instruments_url = (
    "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"
)
```

Change the new live catalog to:

```python
UPSTOX_INSTRUMENTS_URL = (
    "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz"
)
```

Upstox now explicitly recommends the JSON BOD instrument file and says its CSV instrument files are being deprecated. The JSON contains equities, futures, options and indices; it is normally refreshed around 6 AM. Upstox also recommends using `instrument_key` rather than `exchange_token`. ([Upstox - Online Stock and Share Trading][3])

That JSON should become the source of truth for your live selector.

---

## 3. Build a local option catalog from Upstox

Don't call an API every time the user types in the search box.

Download the BOD JSON once and construct indexes like:

```python
underlying_to_contracts: dict[str, list[OptionContract]]
underlying_to_expiries: dict[str, list[date]]
symbol_to_underlying_key: dict[str, str]
instrument_key_to_contract: dict[str, OptionContract]
```

For example:

```python
options = [
    row
    for row in instruments
    if row.get("instrument_type") in {"CE", "PE"}
]

stock_options = [
    row for row in options
    if row.get("underlying_type") == "EQUITY"
]

index_options = [
    row for row in options
    if row.get("underlying_type") == "INDEX"
]

commodity_options = [
    row for row in options
    if row.get("underlying_type") == "COM"
]
```

The current Upstox instrument schema includes `underlying_key`, `underlying_symbol`, `underlying_type`, `strike_price`, `expiry`, `instrument_key`, and CE/PE instrument types, including `MCX_FO`. ([Upstox - Online Stock and Share Trading][4])

This gives you essentially:

```text
NIFTY
  2026-08-13
    24200 CE -> NSE_FO|xxxx
    24200 PE -> NSE_FO|yyyy
    24250 CE -> ...
    ...
  2026-08-20
    ...

RELIANCE
  2026-08-27
    ...

CRUDEOIL
  ...
```

---

## 4. One limitation with "NIFTY 200"

I did not find an Upstox developer endpoint that returns **NIFTY 200 constituent membership**. Upstox exposes index instruments themselves and individual NSE instruments, but the instrument schema doesn't identify which equities belong to NIFTY 200. ([Upstox - Online Stock and Share Trading][5])

Your existing project gets index constituents from NSE through `NseIndexConstituents`. 

If the new live system must be **100% Upstox-only at runtime**, I recommend storing:

```text
config/universes/
    nifty50.json
    nifty100.json
    nifty200.json
```

Then intersect that list with Upstox's actual option underlyings:

```python
eligible_nifty200 = nifty200_symbols & upstox_fo_underlyings
```

Your UI can then correctly call the group:

> **NIFTY 200 · F&O available**

Stocks without listed options simply won't appear.

Alternatively, expose an **All NSE F&O Stocks** group, which can be derived entirely from Upstox.

---

# 5. Commodities need slightly different treatment

This is important.

Upstox explicitly says its `/v2/option/chain` Put/Call Chain endpoint is **not available for MCX**. ([Upstox - Online Stock and Share Trading][6])

That does **not** stop you from building a live commodity option chain.

For MCX, construct it locally from the Upstox instrument catalog:

```text
MCX_FO
  underlying_type = COM
  instrument_type = CE / PE
        ↓
 group by underlying_symbol
        ↓
 group by expiry
        ↓
 group by strike_price
        ↓
 subscribe instrument_key values over V3 WS
```

Upstox's option-contract schema itself recognizes `MCX_FO`, `MCX`, and `underlying_type=COM`. ([Upstox - Online Stock and Share Trading][7])

So your UI can have:

```text
Universe
├── NIFTY 200 F&O
├── NSE F&O Stocks
├── Indices
│   ├── NIFTY
│   ├── BANKNIFTY
│   └── ...
└── Commodities
    ├── CRUDEOIL
    ├── GOLD
    ├── SILVER
    └── ...
```

all using Upstox as the market-data source.

---

# 6. Add these modules to your existing repository

I would extend the structure in your README like this:

```text
src/nse_data_pipeline/
│
├── application/
│   ├── fetch_service.py
│   └── live_market_hub.py          # NEW
│
├── domain/
│   ├── models.py
│   └── live_models.py              # NEW
│
├── infrastructure/
│   ├── api/
│   │   ├── upstox_client.py
│   │   └── upstox_live.py          # NEW
│   │
│   └── symbol_source/
│       ├── upstox_instruments.py
│       └── upstox_live_catalog.py  # NEW
│
└── live/
    ├── app.py                       # FastAPI
    ├── routes.py
    └── websocket.py
```

Then frontend:

```text
web/
├── app/
│   └── page.tsx
│
├── components/
│   └── market/
│       ├── universe-picker.tsx
│       ├── chain-workspace.tsx
│       ├── option-chain-panel.tsx
│       ├── option-chain-table.tsx
│       ├── movers-table.tsx
│       └── connection-status.tsx
│
├── hooks/
│   └── use-market-feed.ts
│
└── lib/
    ├── market-store.ts
    └── market-types.ts
```

---

# 7. Make `LiveMarketHub` the deep module

Give the rest of your application a very small interface:

```python
class LiveMarketHub:
    async def watch_chain(
        self,
        owner_id: str,
        underlying_key: str,
        expiry: str,
    ) -> ChainDefinition:
        ...

    async def unwatch(self, owner_id: str) -> None:
        ...

    def snapshot(self, instrument_keys: set[str]) -> dict:
        ...
```

Its implementation hides:

```text
Upstox authentication
WS authorization
connection lifecycle
protobuf decoding
reconnection
subscriptions
unsubscriptions
reference counting
subscription budgets
latest-price cache
% change calculation
browser broadcasting
```

The official Upstox Python SDK already provides `MarketDataStreamerV3` with `subscribe`, `unsubscribe`, `change_mode`, disconnect, and auto-reconnect facilities, so I would use it instead of manually maintaining the Protobuf implementation initially. ([GitHub][2])

---

# 8. Reference-count subscriptions

This is essential when you have many cards.

Suppose:

```text
Card 1 = NIFTY Aug-13
Card 2 = NIFTY Aug-20
Card 3 = RELIANCE Aug-27
```

Maintain:

```python
subscriptions = {
    "NSE_FO|123": 1,
    "NSE_FO|456": 2,
    "NSE_FO|789": 1,
}
```

When a card opens:

```python
new_keys = requested_keys - currently_subscribed
streamer.subscribe(new_keys, "ltpc")
```

When it closes:

```python
refcount[key] -= 1

if refcount[key] == 0:
    streamer.unsubscribe([key])
```

Never blindly subscribe/unsubscribe everything whenever React re-renders.

---

# 9. Your shadcn UI

I would make it look like this:

```text
┌─────────────────────────────────────────────────────────────────────┐
│ Options Monitor              ● Upstox Live       1,842 / 5,000 keys │
├─────────────────────┬───────────────────────────────────────────────┤
│ Underlyings         │ NIFTY                         [13 Aug ▼] [×]  │
│                     │ Spot 24,612.40   WS ●                          │
│ [ Search...       ] │                                               │
│                     │ [ Option Chain ] [ % Movers ]                 │
│ NIFTY 200           │                                               │
│ ☑ RELIANCE          │ CE %     CE LTP   Strike    PE LTP     PE %  │
│ ☑ HDFCBANK          │ +14.2%    142.30   24500     98.40     -4.2% │
│ □ INFY              │ +11.8%    113.10   24550    111.00     +2.1% │
│ □ ICICIBANK         │  +8.1%     89.40   24600    138.20     +6.3% │
│                     │                                               │
│ Indices             ├───────────────────────────────────────────────┤
│ ☑ NIFTY             │ RELIANCE                    [27 Aug ▼] [×]   │
│ □ BANKNIFTY         │ ...                                           │
│                     │                                               │
│ Commodities         │                                               │
│ □ GOLD              │                                               │
│ □ CRUDEOIL          │                                               │
└─────────────────────┴───────────────────────────────────────────────┘
```

Use these shadcn pieces:

```bash
pnpm dlx shadcn@latest add \
  badge button card checkbox command combobox \
  popover resizable scroll-area select separator \
  skeleton table tabs tooltip
```

For the tables:

```bash
pnpm add @tanstack/react-table @tanstack/react-virtual
```

shadcn's current Data Table guidance is based on TanStack Table and supports custom sorting/filtering, while `Combobox`, `ScrollArea`, `Tabs`, and `Resizable` fit this dashboard structure well. ([Shadcn UI][8])

---

# 10. Don't destroy the option-chain layout by sorting it

There's a UI problem with "option chain sorted by percentage change."

A normal chain should remain:

```text
CE | STRIKE | PE
```

sorted by **strike**.

If you sort those rows by percentage change, the chain becomes difficult to read.

I'd therefore give each card two views:

```text
[ Chain ] [ Movers ]
```

### Chain

```text
CE %     CE LTP    STRIKE    PE LTP    PE %
+5.3       184     24500       73      -4.2
+8.7       152     24550       91      +1.3
...
```

Strike sorted.

### Movers

Flatten the contracts:

```text
Contract                  Type   Strike   LTP      Change
NIFTY 24550 CE            CE     24550    152.00   +18.4%
NIFTY 24700 PE            PE     24700     98.50   +15.1%
NIFTY 24450 CE            CE     24450    201.80   +12.8%
...
```

Sorted by `% change`.

That gives you exactly the scanner you want without compromising the chain.

---

# 11. Example shadcn panel shape

```tsx
<Card className="min-w-[760px]">
  <CardHeader className="flex-row items-center justify-between">
    <div>
      <CardTitle>NIFTY</CardTitle>
      <CardDescription>
        Spot 24,612.40 · 13 Aug 2026
      </CardDescription>
    </div>

    <div className="flex gap-2">
      <Badge variant="outline">LIVE</Badge>
      <Select>{/* expiry */}</Select>
    </div>
  </CardHeader>

  <CardContent>
    <Tabs defaultValue="chain">
      <TabsList>
        <TabsTrigger value="chain">Option Chain</TabsTrigger>
        <TabsTrigger value="movers">% Movers</TabsTrigger>
      </TabsList>

      <TabsContent value="chain">
        <OptionChainTable />
      </TabsContent>

      <TabsContent value="movers">
        <OptionMoversTable />
      </TabsContent>
    </Tabs>
  </CardContent>
</Card>
```

And your workspace:

```tsx
<div className="grid gap-4 xl:grid-cols-2">
  {selectedChains.map((chain) => (
    <OptionChainPanel
      key={`${chain.underlyingKey}:${chain.expiry}`}
      chain={chain}
    />
  ))}
</div>
```

---

# 12. Browser ↔ backend protocol

Don't send the Upstox token to React.

Browser asks your Python backend:

```json
{
  "op": "watch",
  "id": "nifty-2026-08-13",
  "underlying_key": "NSE_INDEX|Nifty 50",
  "expiry": "2026-08-13"
}
```

Backend resolves all contracts and subscribes to Upstox.

Browser receives batches:

```json
{
  "type": "ticks",
  "ticks": [
    {
      "instrument_key": "NSE_FO|12345",
      "ltp": 152.4,
      "cp": 131.2,
      "pct_change": 16.1585,
      "timestamp": 1786410029000
    },
    {
      "instrument_key": "NSE_FO|12346",
      "ltp": 91.25,
      "cp": 93.4,
      "pct_change": -2.3019,
      "timestamp": 1786410029001
    }
  ]
}
```

Batch browser updates every roughly 100–250 ms rather than forcing React to re-render on every individual tick.

---

# 13. Authentication: use Analytics Token for this dashboard

Since this application is read-only market analysis, the current **Upstox Analytics Token** is particularly well suited: Upstox says it has one-year validity and supports Market Data Feed V3, WebSocket authorization, option chains, option contracts, Instrument Search and market-data endpoints. ([Upstox - Online Stock and Share Trading][9])

Use:

```env
UPSTOX_ANALYTICS_TOKEN=xxxxxxxx
```

**Server only.**

Never:

```env
NEXT_PUBLIC_UPSTOX_TOKEN=...
```

A normal OAuth access token currently expires at 3:30 AM the following day, so it is much less convenient for an always-on read-only dashboard. ([Upstox - Online Stock and Share Trading][10])

---

# 14. WebSocket connection sequence

Your live module should do:

```text
Backend starts
    ↓
GET V3 market-data-feed authorize
    ↓
receive one-time wss:// URL
    ↓
connect
    ↓
subscribe active instrument keys as LTPC
    ↓
Upstox snapshot
    ↓
live ticks
    ↓
update QuoteStore
    ↓
broadcast small JSON patches to browser
```

The V3 authorize endpoint returns a WebSocket URL whose authorization code is **single-use**, so a fresh authorization URL should be obtained when establishing a new connection. ([Upstox - Online Stock and Share Trading][11])

V3 also sends an initial market-status tick followed by a market snapshot and then continuing live updates. ([upstox.com][1])

---

# 15. Subscription budget must be visible in the UI

This is something I would definitely add:

```text
Market Feed
● Connected
1,842 / 5,000 LTPC
36.8%
```

Before opening another chain:

```python
required = active_keys | new_chain_keys

if len(required) > 5000:
    raise SubscriptionLimitExceeded(...)
```

And show:

```text
Can't subscribe to BANKNIFTY

This chain requires 412 contracts.
Current subscription: 4,784 / 5,000.

Close another chain or choose fewer expiries.
```

Because subscribing to the **full option chains of every NIFTY 200 stock simultaneously is not realistic within a 5,000-instrument feed limit**. The right model is unlimited entries in the watchlist but a limited number of simultaneously active live-chain panels. ([upstox.com][1])

---

# 16. The implementation order I would follow

1. Replace the CSV-based instrument source for this feature with Upstox BOD JSON.
2. Add `UpstoxLiveCatalog` and build mappings by underlying/expiry/strike/type.
3. Add an Upstox Analytics Token on the Python backend.
4. Add `LiveMarketHub` around `MarketDataStreamerV3`.
5. Implement reference-counted `watch_chain()` / `unwatch()`.
6. Add an in-memory `QuoteStore`.
7. Calculate `% change` from LTP and previous close.
8. Add a small FastAPI WebSocket endpoint for your browser.
9. Create the Next.js/shadcn application.
10. Add the underlying multi-select with **NIFTY 200 F&O / Indices / Commodities** groups.
11. Create one reusable `OptionChainPanel` per active underlying.
12. Add `Chain` and `% Movers` tabs.
13. Add virtualized rows and 100–250 ms rendering batches.
14. Add the `x / 5000` subscription-budget indicator.
15. Add reconnect → reauthorize → resubscribe tests.

This keeps the historical side of your existing pipeline intact while adding a separate, clean **live-data path**. It also keeps every external market-data dependency restricted to Upstox REST/assets/WebSocket, as requested. ([Upstox - Online Stock and Share Trading][3])

[1]: https://upstox.com/developer/api-documentation/v3/get-market-data-feed/?utm_source=chatgpt.com "Market Data Feed V3 API | Upstox Developer API"
[2]: https://github.com/upstox/upstox-python?utm_source=chatgpt.com "GitHub - upstox/upstox-python: Official Python SDK for accessing Upstox API · GitHub"
[3]: https://upstox.com/developer/api-documentation/instruments/ "Instruments | Upstox Developer API"
[4]: https://upstox.com/developer/api-documentation/instruments/?utm_source=chatgpt.com "Instruments | Upstox Developer API"
[5]: https://upstox.com/developer/api-documentation/instrument-search/ "Search Instruments API | Upstox Developer API"
[6]: https://upstox.com/developer/api-documentation/get-pc-option-chain/ "Put/Call Option Chain API | Upstox Developer API"
[7]: https://upstox.com/developer/api-documentation/get-option-contracts/ "Option Contracts API | Upstox Developer API"
[8]: https://ui.shadcn.com/docs/components/base/data-table?utm_source=chatgpt.com "Data Table - shadcn/ui"
[9]: https://upstox.com/developer/api-documentation/analytics-token/?utm_source=chatgpt.com "Analytics Token | Upstox Developer API"
[10]: https://upstox.com/developer/api-documentation/get-token/?utm_source=chatgpt.com "Get Token API | Upstox Developer API"
[11]: https://upstox.com/developer/api-documentation/get-market-data-feed-authorize-v3/?utm_source=chatgpt.com "Market Data Feed Authorize Url V3 API | Upstox Developer API"
