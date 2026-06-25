# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project goal

Build the most accurate historical record of **El Niño effects on commodity production outcomes** (yield, weight, harvest volume, stocks, supply balance) so that an analyst can draw defensible conclusions about how the **2026 El Niño** will affect each commodity.

**Hard rule — enforced everywhere in the codebase:** never use historical price data. Only production quantities, yield per hectare, harvest weight, ending stocks, and stocks-to-use ratios. This applies to the data block, the charts, the AI prompt, and any new feature. If a source gives prices, discard it.

The 9 commodities are: cocoa, palm oil, sugar, coffee, rice, bananas, wheat, corn, soybean.

---

## Running the dashboard

```powershell
# Start the server (picks up new static files immediately, no restart needed for JS/JSON edits)
powershell -ExecutionPolicy Bypass -File serve.ps1 -Port 3456

# If port 3456 is stuck from a prior session, use 3457:
powershell -ExecutionPolicy Bypass -File serve.ps1 -Port 3457
```

Open **http://localhost:3456/** in a browser. The dashboard is also openable as a raw `file://` URL but the `/proxy/*` routes (NOAA ONI) and `/supply-data.json` require the server.

---

## Architecture

Everything is a single file: **`index.html`** (~1150 lines). There is no build step, no npm, no Node. The file is structured in this order:

1. **CSS** — dark theme via CSS custom properties (`--bg`, `--surface`, `--accent`, etc.)
2. **HTML skeleton** — header + sidebar (static) + `<main id="content">` (wiped and rewritten on every navigation)
3. **`<script>`** containing, in order:
   - **Data block** (`const C = { cocoa:{...}, ... }`) — raw inputs only, no computed values
   - **Compute layer** (`computeStats`, `computeConviction`, `STATS` cache) — all arithmetic lives here
   - **Live data layer** — three async fetches, results applied via `applySupplyData` / `applyCerealTrend`
   - **AI agent** — `buildContext`, `callAI`, `runAI`
   - **Render** — `overview()`, `detail(k)`, `renderSidebar()`, `chartEvents()`, `chartTrend()`
   - **Init** — `fetchAllLiveData(false)` then `render()`

### Data block schema

```js
C['cocoa'] = {
  name, icon, cls,          // cls: 'neg' | 'pos' | 'mix'
  score,                    // 0–1 sensitivity rank (hand-set from sources)
  unit,                     // label for chart y-axis
  regions, driver, mech,    // narrative fields
  wx:[{l:'label', t:'type'}],   // t: drought|rain|heat|disease|good
  why:[...],                // bullet list of structural reasons for exposure
  events:{
    '2002-03':{dev:-6, src:'est'},   // dev = YoY % deviation
    '2023-24':{dev:-11, src:'rep'},  // src: 'rep' = sourced, 'est' = directional estimate
    // Alt form when you have real numbers: {prod:3200, base:3600, src:'rep'}
  },
  supply:{ stocks:null, use:null, src:'todo' },  // overwritten by supply-data.json at runtime
  superNote,   // text about the 2014-16 or 2023-24 super event
  trendIdx:{ labels:[...], vals:[...] },  // illustrative until live data loads
  verdict,     // 'BUMPER' | 'TROUGH' | 'MIXED'
  verdictNote,
  predict, dir, dirColor,   // 2026 house view
  tiles:{ 'Label':{v:'value', d:'up|down|flat', n:'note'}, ... },
  geo:{lat, lon, place}     // for Open-Meteo live weather
}
```

`src:'rep'` renders as a solid bar; `src:'est'` renders faded with a `*` marker. Always use `'rep'` when a figure comes from ICCO, USDA WASDE, FAO, or a named broker report, and `'est'` otherwise.

### Compute layer

`computeStats(c)` and `computeConviction(s)` are pure functions — every number shown in the UI is derived here, not hand-typed. The AI agent is fed these pre-computed values and explicitly barred from doing its own arithmetic. **Do not add hand-computed statistics to the data block.**

Conviction formula: `0.55 × consistencyN + 0.30 × magnitudeN + 0.15 × tightnessN`

### Live data sources (confirmed working)

| Source | Route | Commodities |
|--------|-------|-------------|
| NOAA CPC ONI | `/proxy/oni` via serve.ps1 | ENSO header pill |
| World Bank `AG.PRD.CREL.MT` | direct fetch (no CORS) | wheat, corn, rice trend |
| `supply-data.json` | static file via serve.ps1 | all 9 — stocks-to-use ratios |

**USDA FAS PSD** (404) and **FAO FAOSTAT** (521 Cloudflare) are both currently unreachable. Do not attempt to re-add proxy routes for them without verifying the endpoint first.

Live data is cached in `sessionStorage` under key `en_live_v3` for 1 hour. The 📡 badge forces a refresh.

### Updating stocks-to-use ratios

Edit **`supply-data.json`** monthly with values from the [USDA WASDE PDF](https://www.usda.gov/oce/commodity/wasde/) or ICCO Quarterly Bulletin. Format:

```json
"wheat": { "stu": 0.337, "src": "USDA WASDE est.", "marketYear": "2025/26", "qual": "est" }
```

`bananas` and `coffee` have `stu:null` intentionally (perishable / not standardly reported).

### Improving historical data accuracy

The primary gap is that most event-year deviations are `src:'est'` (directional estimates). To improve accuracy:

1. **Replace `dev` estimates with real figures** from ICCO annual reports, USDA WASDE historical PDFs, or the Barclays/Citi research cited in the footer. Change `src:'est'` → `src:'rep'` when you do.
2. **Use the `{prod, base}` form** when you have absolute production numbers from two consecutive seasons — `evDev()` computes the exact YoY % rather than relying on an estimate.
3. **Add more events** by extending `EVENTS` to include older years (1997-98, 1982-83) as data is found. Add them as keys in each commodity's `events` object; the compute layer handles variable-length series automatically.

The most data-sparse commodities are bananas, coffee, and palm oil. Cocoa 2023-24 (`dev:-11, src:'rep'`) is the highest-confidence data point; wheat and soybean recent years are well-sourced from WASDE.

### AI agent

The AI receives a `buildContext(k)` string containing all pre-computed stats and is governed by `STRICT RULES` that prohibit arithmetic, price references, and invented figures. When adding new statistics to the compute layer, add them to `buildContext` so the AI can cite them. Do not loosen the AI's rules — the value of this tool depends on the AI citing verifiable computed numbers, not generating its own estimates.
