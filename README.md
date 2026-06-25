# 🌊 El Niño Commodity Intelligence — AI Agent

A clean, single-file dashboard that predicts **how the 2026 El Niño will hit commodity supply**, built for Rubric Capital research. It covers 10 commodities, grounds every call in **production numbers** (not price history), and includes a built-in **AI agent** (Claude or Gemini) plus **live weather** from each crop's key growing region.

---

## ▶️ How to open in VS Code

The whole app is one file — `index.html`. No build step, no install.

**Option A — just open it (simplest)**
1. Open the `elnino-dashboard` folder in VS Code (`File → Open Folder`).
2. Right-click `index.html` → **Reveal in File Explorer** → double-click to open in your browser.

**Option B — Live Server (recommended, nicer reloads)**
1. Install the **Live Server** extension (by Ritwick Dey) from the Extensions panel.
2. Right-click `index.html` → **Open with Live Server**.

**Option C — quick local server (no extensions)**
- Double-click `serve.ps1`, or run in a terminal:
  ```powershell
  powershell -ExecutionPolicy Bypass -File serve.ps1
  ```
  Then open <http://localhost:3456/>.

> The live-weather and AI features work from a plain `file://` open too — but Live Server / Option C avoid any browser quirks.

---

## 🤖 Turning on the AI agent

1. Click **⚙️ AI Setup** (top-right).
2. Pick a provider — **Claude** or **Gemini** — and paste your API key.
   - Claude key: <https://console.anthropic.com/>
   - Gemini key: <https://aistudio.google.com/apikey>
3. On any commodity page, click **✨ Generate full supply analysis**, or type a custom question into **Ask the agent…**.

The agent is *grounded*: it receives a production dossier for the selected commodity (regions, weather mechanism, El Niño track record, recent harvest verdict, house 2026 view) and is told to reason about **supply, not prices**.

🔒 Keys stay in your browser tab only (sessionStorage) and go straight to the provider — never to any server.

---

## 📊 What each commodity dashboard shows

| Section | What it answers |
|---|---|
| **Mechanism + weather chips** | *Why* it's affected — drought, excess rain, heat, disease, or beneficial conditions |
| **Why highly exposed** | The structural reasons the impact is large |
| **Production impact in past El Niño events** | Yield/production deviation across the last ~20 years of events |
| **Average El Niño impact** | Mean across all events + the super-event (2014–16) figure |
| **Recent production trajectory** | Are we coming off a **bumper** or a **trough**? |
| **Bumper-or-trough verdict** | Production, planted area, yield and stocks at a glance |
| **Live weather** | Current temp / humidity / 7-day rain in the key growing region (Open-Meteo) |
| **2026 outlook** | The house production forecast, with conviction and direction |
| **AI agent** | On-demand deep analysis (Claude / Gemini) |

---

## 🔑 Key findings (production-based)

- **Negative for supply:** Cocoa, Palm Oil, Coffee (Robusta), Rice, Bananas (flood, not drought), Fishmeal/Fish Oil.
- **Mixed / two-sided:** Sugar (Asia down, Brazil steadier), Wheat (global resilient, Australia hit), Corn (US fine, Brazil safrinha risk).
- **Positive for supply:** **Soybean** — global yields tend to rise +2–5%, Argentina a clear beneficiary.
- **Cocoa is the single most sensitive:** ICCO finds 20 of the last 21 El Niño years hurt production; 2023–24 fell ~11% YoY.
- **Most are entering 2026 differently:** grains (wheat, corn, soybean) come off **bumper** crops with comfortable stocks; cocoa and fishmeal come off **troughs** with thin buffers — so the same weather shock bites much harder there.

---

## 📚 Sources & methodology

- **Research:** Citi Research El Niño call · Barclays Cross-Asset "Super El Niño: The Climate Risk Trade" (15 May 2026) · WFP / Action Against Hunger "El Niño 2023–24, Latin America & the Caribbean".
- **Production data:** ICCO (cocoa), USDA PSD, India IMD, Peru anchovy quotas (IMARPE), and the nature.com ENSO crop-yield meta-analysis cited by Barclays.
- **Live regional weather:** [Open-Meteo](https://open-meteo.com/) (free, no key).
- **AI analysis:** Anthropic Claude & Google Gemini APIs.
- Per the brief, **no historical commodity price levels are used** — only production / supply / yield. Trajectory bars marked *indexed/illustrative* depict the documented direction, not an exact reported series.

*For research purposes only — not investment advice.*
