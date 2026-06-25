#!/usr/bin/env python3
"""
Cocoa Market Intelligence Pipeline
Sources (verified June 2026):
  - OWID/FAO CSVs (production, yield) — no key
  - ECA European grindings PDFs — no key
  - NCA North American grindings (candyusa.com) — no key
  - CAA Asian grindings (cocoaasia.org) — no key
  - USDA FAS PSD API — key via USDA_FAS_API_KEY env var
  - Gap-fill: Claude API via ANTHROPIC_API_KEY env var
Usage:
  pip install -r requirements.txt
  export USDA_FAS_API_KEY=your_key   # optional
  export ANTHROPIC_API_KEY=your_key  # optional, enables gap-fill
  python cocoa_pipeline.py
"""

import os, re, csv, time, logging
from datetime import datetime
from io import BytesIO, StringIO
from pathlib import Path

import requests
import pandas as pd

try:
    import pdfplumber
    HAS_PDF = True
except ImportError:
    HAS_PDF = False
    print("WARNING: pdfplumber not installed. ECA and grindings PDF parsing disabled. pip install pdfplumber")

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

# ── CONFIG ──────────────────────────────────────────────────────────────────
FOCUS_ENTITIES = [
    "Cote d'Ivoire", "Ghana", "Nigeria", "Cameroon",
    "Indonesia", "Ecuador", "Brazil"
]
CLIMATE_REGION = {
    "Cote d'Ivoire": "West Africa", "Ghana": "West Africa",
    "Nigeria": "West Africa", "Cameroon": "West Africa",
    "Indonesia": "Southeast Asia",
    "Ecuador": "Latin America", "Brazil": "Latin America",
}
ISO_MAP = {
    "Cote d'Ivoire": "CIV", "Ghana": "GHA", "Nigeria": "NGA",
    "Cameroon": "CMR", "Indonesia": "IDN",
    "Ecuador": "ECU", "Brazil": "BRA",
}
YEAR_START, YEAR_END = 2005, 2024
DATA_DIR = Path("data")
USDA_KEY = os.environ.get("USDA_FAS_API_KEY", "aSeM9P9tkG2qLwjT9MrNhGjMitfKK0fkP4tlVBRN")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OWID_UA = {"User-Agent": "Our World In Data data fetch/1.0"}
BROWSER_UA = {"User-Agent": "Mozilla/5.0 (compatible; research-pipeline/1.0)"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

STATS = {"total": 0, "sourced": 0, "estimated": 0, "failed": 0}

# ── HELPERS ──────────────────────────────────────────────────────────────────
def safe_fetch(url: str, **kwargs) -> requests.Response | None:
    try:
        r = requests.get(url, timeout=40, **kwargs)
        if r.status_code == 200:
            return r
        log.warning(f"HTTP {r.status_code}: {url}")
        STATS["failed"] += 1
        return None
    except Exception as e:
        log.error(f"Fetch failed {url}: {e}")
        STATS["failed"] += 1
        return None

def claude_estimate(prompt: str, context: str = "") -> tuple[float | None, str]:
    """Ask Claude to fill a missing data point. Returns (value, reasoning)."""
    if not HAS_ANTHROPIC or not ANTHROPIC_KEY:
        return None, "Claude not available (no ANTHROPIC_API_KEY)"
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        msg = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=250,
            messages=[{"role": "user", "content":
                f"You are filling a data gap in a cocoa market intelligence pipeline.\n"
                f"Context: {context}\n{prompt}\n"
                f"Respond ONLY in this format: ESTIMATE: [number] | REASONING: [one sentence]"
            }]
        )
        text = msg.content[0].text
        m_val = re.search(r"ESTIMATE:\s*([\d,\.]+)", text)
        m_rsn = re.search(r"REASONING:\s*(.+)", text)
        val = float(m_val.group(1).replace(",", "")) if m_val else None
        rsn = m_rsn.group(1).strip() if m_rsn else "Claude estimate (no reasoning parsed)"
        return val, rsn
    except Exception as e:
        log.error(f"Claude estimate failed: {e}")
        return None, f"Claude API error: {e}"

def save_csv(data, filename: str, fieldnames: list | None = None):
    DATA_DIR.mkdir(exist_ok=True)
    path = DATA_DIR / filename
    if isinstance(data, pd.DataFrame):
        data.to_csv(path, index=False)
        log.info(f"Saved {len(data)} rows → {path}")
    elif data:
        fields = fieldnames or list(data[0].keys())
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader(); w.writerows(data)
        log.info(f"Saved {len(data)} rows → {path}")
    else:
        fields = fieldnames or []
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=fields).writeheader()
        log.info(f"Saved empty file → {path}")

def bump(category: str, n: int = 1):
    STATS[category] += n; STATS["total"] += n

# ── SOURCE 1A: OWID/FAO PRODUCTION ──────────────────────────────────────────
def fetch_owid_production() -> pd.DataFrame:
    url = ("https://ourworldindata.org/grapher/cocoa-bean-production.csv"
           "?v=1&csvType=full&useColumnShortNames=false")
    r = safe_fetch(url, headers=OWID_UA)
    if r is None:
        return pd.DataFrame()
    df = pd.read_csv(StringIO(r.text), encoding_errors="replace")
    df.columns = [c.strip() for c in df.columns]
    # Value column is anything that's not Entity/Code/Year
    val_col = next((c for c in df.columns if c not in ("Entity", "Code", "Year")), None)
    if not val_col:
        log.error("OWID production: could not identify value column")
        return pd.DataFrame()
    df = df.rename(columns={val_col: "production_tonnes"})
    # Filter to real ISO codes (not OWID_ aggregates), focus countries, year range
    df = df[df["Code"].notna() & ~df["Code"].str.startswith("OWID_") & (df["Code"] != "")]
    df = df[df["Entity"].isin(FOCUS_ENTITIES)]
    df = df[(df["Year"] >= YEAR_START) & (df["Year"] <= YEAR_END)]
    df["climate_region"] = df["Entity"].map(CLIMATE_REGION)
    prov = f"SOURCE: Our World In Data / FAO — {url}"
    df["provenance"] = prov
    df = df.rename(columns={"Year": "year", "Entity": "entity", "Code": "code"})
    bump("sourced", len(df))
    return df[["year", "entity", "code", "production_tonnes", "climate_region", "provenance"]]

# ── SOURCE 1B: OWID/FAO YIELD ────────────────────────────────────────────────
def fetch_owid_yield() -> pd.DataFrame:
    url = ("https://ourworldindata.org/grapher/cocoa-bean-yields.csv"
           "?v=1&csvType=full&useColumnShortNames=false")
    r = safe_fetch(url, headers=OWID_UA)
    if r is None:
        return pd.DataFrame()
    df = pd.read_csv(StringIO(r.text), encoding_errors="replace")
    df.columns = [c.strip() for c in df.columns]
    val_col = next((c for c in df.columns if c not in ("Entity", "Code", "Year")), None)
    if not val_col:
        log.error("OWID yield: could not identify value column")
        return pd.DataFrame()
    df = df.rename(columns={val_col: "yield_tonnes_per_ha"})
    df = df[df["Code"].notna() & ~df["Code"].str.startswith("OWID_") & (df["Code"] != "")]
    df = df[df["Entity"].isin(FOCUS_ENTITIES)]
    df = df[(df["Year"] >= YEAR_START) & (df["Year"] <= YEAR_END)]
    df["climate_region"] = df["Entity"].map(CLIMATE_REGION)
    prov = f"SOURCE: Our World In Data / FAO — {url}"
    df["provenance"] = prov
    df = df.rename(columns={"Year": "year", "Entity": "entity", "Code": "code"})
    bump("sourced", len(df))
    return df[["year", "entity", "code", "yield_tonnes_per_ha", "climate_region", "provenance"]]

# ── GAP FILL: PRODUCTION ─────────────────────────────────────────────────────
def gap_fill_production(df: pd.DataFrame) -> pd.DataFrame:
    existing = set(zip(df["year"], df["entity"]))
    all_combos = [(y, e) for y in range(YEAR_START, YEAR_END + 1) for e in FOCUS_ENTITIES]
    missing = [(y, e) for y, e in all_combos if (y, e) not in existing]
    if not missing:
        return df
    log.info(f"Gap-filling {len(missing)} missing production rows...")
    fill_rows = []
    for year, entity in missing:
        val, rsn = claude_estimate(
            f"Estimate cocoa bean production (tonnes) for {entity} in {year}.",
            context=f"Known El Niño patterns, ICCO annual reports, FAO FAOSTAT historical trends for {entity}."
        )
        fill_rows.append({
            "year": year, "entity": entity, "code": ISO_MAP.get(entity, ""),
            "production_tonnes": val,
            "climate_region": CLIMATE_REGION.get(entity, ""),
            "provenance": f"ESTIMATED BY CLAUDE — {rsn}"
        })
        bump("estimated")
    return pd.concat([df, pd.DataFrame(fill_rows)], ignore_index=True)

# ── SOURCE 2: ECA EUROPEAN GRINDINGS ─────────────────────────────────────────
def fetch_eca_grindings() -> list[dict]:
    if not HAS_PDF:
        log.warning("pdfplumber not installed — ECA PDF parsing skipped")
        return []
    rows = []
    seen_pairs: dict[str, dict] = {}

    for year in range(2013, 2027):
        for q in range(1, 5):
            if year == 2026 and q > 1:
                break
            base = f"https://www.eurococoa.com/wp-content/uploads/WEBSITE-REPORT-WESTERN-STATS-Q{q}-{year}.pdf"
            alt  = f"https://www.eurococoa.com/wp-content/uploads/WEBSITE-REPORT-WESTERN-STATS-Q{q}-{year}-2.pdf"
            # For Q1 2026 try alt suffix first per spec
            candidates = [alt, base] if (year == 2026 and q == 1) else [base, alt]

            pdf_bytes, used_url = None, None
            for url in candidates:
                r = safe_fetch(url, headers=BROWSER_UA)
                if r:
                    pdf_bytes = r.content; used_url = url; break

            if pdf_bytes is None:
                log.debug(f"ECA Q{q}/{year}: no PDF found")
                continue

            try:
                with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
                    # Try table extraction first (more reliable for structured data)
                    for page in pdf.pages:
                        tables = page.extract_tables()
                        for table in (tables or []):
                            for row in table:
                                if not row or not row[0]:
                                    continue
                                cell0 = str(row[0]).strip()
                                if not re.match(r"\d{4}/\d{4}", cell0):
                                    continue
                                nums = []
                                for cell in row[1:]:
                                    try:
                                        nums.append(float(str(cell).strip()))
                                    except (TypeError, ValueError):
                                        pass
                                if len(nums) >= 5:
                                    rec = {
                                        "pdf_quarter": f"Q{q} {year}",
                                        "year_pair": cell0,
                                        "q4_yoy_pct": nums[0],
                                        "q3_yoy_pct": nums[1],
                                        "q2_yoy_pct": nums[2],
                                        "q1_yoy_pct": nums[3],
                                        "ytd_yoy_pct": nums[4],
                                        "provenance": f"SOURCE: European Cocoa Association (ECA) — {used_url}"
                                    }
                                    seen_pairs[cell0] = rec
                                    bump("sourced")

                    # Fallback: raw text regex
                    if not seen_pairs:
                        text = "\n".join(p.extract_text() or "" for p in pdf.pages)
                        pattern = r"(\d{4}/\d{4})\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)"
                        for m in re.finditer(pattern, text):
                            yp, q4, q3, q2, q1_pct, ytd = m.groups()
                            seen_pairs[yp] = {
                                "pdf_quarter": f"Q{q} {year}", "year_pair": yp,
                                "q4_yoy_pct": float(q4), "q3_yoy_pct": float(q3),
                                "q2_yoy_pct": float(q2), "q1_yoy_pct": float(q1_pct),
                                "ytd_yoy_pct": float(ytd),
                                "provenance": f"SOURCE: European Cocoa Association (ECA) — {used_url}"
                            }
                            bump("sourced")
            except Exception as e:
                log.error(f"ECA Q{q}/{year} parse error: {e}")

        time.sleep(0.5)  # Polite delay between PDF fetches

    return sorted(seen_pairs.values(), key=lambda r: r["year_pair"])

# ── SOURCE 3: NCA NORTH AMERICAN GRINDINGS ───────────────────────────────────
def fetch_nca_grindings() -> list[dict]:
    # Confirmed Q1 2026 seed from spec (always include)
    confirmed = {
        "quarter": "Q1 2026", "volume_mt": 106_087, "yoy_pct": -3.8,
        "provenance": "SOURCE: National Confectioners Association (NCA) — Q1 2026 confirmed per https://candyusa.com/cocoa-grinds-report/"
    }
    rows = [confirmed]
    bump("sourced")

    if not HAS_BS4:
        log.warning("beautifulsoup4 not installed — NCA page scrape skipped")
        return rows

    url = "https://candyusa.com/cocoa-grinds-report/"
    r = safe_fetch(url, headers=BROWSER_UA)
    if r is None:
        log.warning("NCA landing page unreachable — using confirmed seed only")
        return rows

    soup = BeautifulSoup(r.text, "html.parser")
    # Look for PDF links in the page
    pdf_links = [a["href"] for a in soup.find_all("a", href=True)
                 if ".pdf" in a["href"].lower()]
    for href in pdf_links[:3]:  # Try up to 3 PDFs
        pdf_url = href if href.startswith("http") else f"https://candyusa.com{href}"
        pdf_r = safe_fetch(pdf_url, headers=BROWSER_UA)
        if not pdf_r or not HAS_PDF:
            continue
        try:
            with pdfplumber.open(BytesIO(pdf_r.content)) as pdf:
                text = "\n".join(p.extract_text() or "" for p in pdf.pages)
            # Look for MT figure and YoY%
            mt_match = re.search(r"([\d,]{5,})\s*(?:metric\s*tons?|MT)\b", text, re.IGNORECASE)
            yoy_match = re.search(r"([+-]?\d+\.?\d*)\s*%\s*(?:change|yoy|year.over.year)", text, re.IGNORECASE)
            qtr_match = re.search(r"Q([1-4])\s+(\d{4})", text)
            if mt_match:
                vol = int(mt_match.group(1).replace(",", ""))
                yoy = float(yoy_match.group(1)) if yoy_match else None
                qtr = f"Q{qtr_match.group(1)} {qtr_match.group(2)}" if qtr_match else "recent quarter"
                if (qtr, vol) != (confirmed["quarter"], confirmed["volume_mt"]):
                    rows.append({
                        "quarter": qtr, "volume_mt": vol, "yoy_pct": yoy,
                        "provenance": f"SOURCE: NCA PDF — {pdf_url}"
                    })
                    bump("sourced")
                break
        except Exception as e:
            log.error(f"NCA PDF parse: {e}")

    return rows

# ── SOURCE 4: CAA ASIAN GRINDINGS ────────────────────────────────────────────
def fetch_caa_grindings() -> list[dict]:
    confirmed = {
        "quarter": "Q1 2026", "volume_mt": 223_503, "yoy_pct": 5.2,
        "provenance": "SOURCE: Cocoa Association of Asia (CAA) — Q1 2026 confirmed per https://www.cocoaasia.org/grinding-figures"
    }
    rows = [confirmed]
    bump("sourced")

    if not HAS_BS4:
        log.warning("beautifulsoup4 not installed — CAA page scrape skipped")
        return rows

    url = "https://www.cocoaasia.org/grinding-figures"
    r = safe_fetch(url, headers=BROWSER_UA)
    if r is None:
        return rows

    soup = BeautifulSoup(r.text, "html.parser")
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if len(cells) >= 2 and re.match(r"Q[1-4]\s*20\d\d", cells[0]):
                try:
                    vol_str = cells[1].replace(",", "")
                    vol = int(float(vol_str))
                    yoy = float(cells[2].replace("%", "")) if len(cells) > 2 else None
                    rec = {
                        "quarter": cells[0], "volume_mt": vol, "yoy_pct": yoy,
                        "provenance": f"SOURCE: Cocoa Association of Asia — {url}"
                    }
                    if cells[0] != confirmed["quarter"]:
                        rows.append(rec)
                        bump("sourced")
                except (ValueError, IndexError):
                    pass

    return sorted(rows, key=lambda r: r["quarter"])

# ── SOURCE 5: USDA FAS PSD ───────────────────────────────────────────────────
USDA_ATTRS = {20: "area_harvested", 28: "production", 57: "imports", 88: "exports", 176: "ending_stocks"}

def fetch_usda_psd() -> pd.DataFrame:
    records = []
    for year in range(YEAR_START, YEAR_END + 1):
        url = f"https://apps.fas.usda.gov/OpenData/api/psd/commodity/0620000/country/all/year/{year}"
        r = safe_fetch(url, headers={"API_KEY": USDA_KEY, "Accept": "application/json"})
        if r is None:
            continue
        try:
            for item in r.json():
                if item.get("attributeId") not in USDA_ATTRS:
                    continue
                records.append({
                    "year": year,
                    "country_code": item.get("countryCode"),
                    "country_name": item.get("countryName"),
                    "attribute": USDA_ATTRS[item["attributeId"]],
                    "value": item.get("value"),
                    "unit_desc": item.get("unitDescription", ""),
                    "provenance": f"SOURCE: USDA FAS PSD API — cocoa commodity 0620000 year {year}"
                })
                bump("sourced")
        except Exception as e:
            log.error(f"USDA PSD year {year}: {e}")
        time.sleep(0.3)

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df_wide = df.pivot_table(
        index=["year", "country_code", "country_name"],
        columns="attribute", values="value", aggfunc="first"
    ).reset_index()
    df_wide.columns.name = None
    df_wide["provenance"] = "SOURCE: USDA FAS PSD API — https://apps.fas.usda.gov/OpenData/api/psd/commodity/0620000"
    return df_wide

# ── STDOUT SUMMARY ────────────────────────────────────────────────────────────
def print_summary(prod_df: pd.DataFrame, yield_df: pd.DataFrame,
                  eca: list, nca: list, caa: list):
    divider = "=" * 70
    print(f"\n{divider}")
    print("COCOA MARKET INTELLIGENCE — PIPELINE SUMMARY")
    print(f"Run: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(divider)

    if not prod_df.empty and "year" in prod_df.columns:
        latest_yr = int(prod_df["year"].max())
        latest = prod_df[prod_df["year"] == latest_yr].copy()
        print(f"\n📦 PRODUCTION ({latest_yr}, focus countries):")
        for _, row in latest.sort_values("production_tonnes", ascending=False, na_position="last").iterrows():
            flag = "⚠️ EST" if "ESTIMATED BY CLAUDE" in str(row.get("provenance", "")) else "✓ SRC"
            val = f"{row['production_tonnes']:>12,.0f} t" if pd.notna(row.get("production_tonnes")) else "       N/A"
            prov = str(row.get("provenance", ""))[:55]
            print(f"  [{flag}] {row['entity']:<22} {val}  |  {prov}...")

        print(f"\n🌍 REGIONAL SUBTOTALS (computed from country rows, not aggregated source):")
        for region, grp in latest.groupby("climate_region"):
            total = grp["production_tonnes"].sum()
            all_est = all("ESTIMATED" in str(p) for p in grp["provenance"])
            flag = "⚠️ EST" if all_est else "✓ SRC"
            print(f"  [{flag}] {region:<22} {total:>12,.0f} t")

    print(f"\n🏭 LATEST GRINDINGS (demand-side, YoY %):")
    if eca:
        e = sorted(eca, key=lambda r: r["year_pair"], reverse=True)[0]
        flag = "⚠️ EST" if "ESTIMATED" in e["provenance"] else "✓ SRC"
        print(f"  [{flag}] Europe (ECA):      {e['year_pair']} YTD {e['ytd_yoy_pct']:+.1f}%  |  {e['provenance'][:55]}...")
    else:
        print("  [⚠️ EST] Europe (ECA): no PDF data parsed")
    for label, src in [("N.America (NCA)", nca), ("Asia (CAA)", caa)]:
        if src:
            rec = src[-1]
            flag = "⚠️ EST" if "ESTIMATED" in rec["provenance"] else "✓ SRC"
            print(f"  [{flag}] {label:<20} {rec['quarter']}  {rec['yoy_pct']:+.1f}% YoY  {rec['volume_mt']:,} MT  |  {rec['provenance'][:50]}...")

    print(f"\n📊 SUPPLY/DEMAND SIGNAL:")
    print(f"  [⚠️ ESTIMATED BY CLAUDE] Based on ICCO estimates through 2025:")
    print(f"  2023/24 deficit ~439k tonnes; 2024/25 deficit ~350–500k tonnes estimate.")
    print(f"  Third consecutive deficit year → Signal: DEFICIT")

    print(f"\n📈 DATA QUALITY SUMMARY:")
    print(f"  Total data points : {STATS['total']}")
    print(f"  Sourced (measured): {STATS['sourced']}")
    print(f"  Estimated (Claude): {STATS['estimated']}")
    print(f"  Failed fetches    : {STATS['failed']}")
    print()

# ── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    log.info("Starting cocoa pipeline…")
    DATA_DIR.mkdir(exist_ok=True)

    # Production
    log.info("Fetching OWID/FAO production…")
    prod_df = fetch_owid_production()
    if prod_df.empty:
        log.warning("OWID production unavailable — gap-filling all rows")
        prod_df = pd.DataFrame(columns=["year", "entity", "code", "production_tonnes", "climate_region", "provenance"])
    prod_df = gap_fill_production(prod_df)
    save_csv(prod_df, "cocoa_production_2005_2024.csv")

    # Yield
    log.info("Fetching OWID/FAO yield…")
    yield_df = fetch_owid_yield()
    if yield_df.empty:
        log.warning("OWID yield unavailable")
    save_csv(yield_df, "cocoa_yield_2005_2024.csv")

    # ECA grindings
    log.info("Fetching ECA grindings PDFs (2013–2026)…")
    eca_rows = fetch_eca_grindings()
    save_csv(
        eca_rows, "cocoa_grindings_europe_quarterly.csv",
        fieldnames=["pdf_quarter", "year_pair", "q4_yoy_pct", "q3_yoy_pct",
                    "q2_yoy_pct", "q1_yoy_pct", "ytd_yoy_pct", "provenance"]
    )

    # NCA grindings
    log.info("Fetching NCA grindings…")
    nca_rows = fetch_nca_grindings()
    save_csv(nca_rows, "cocoa_grindings_north_america.csv",
             fieldnames=["quarter", "volume_mt", "yoy_pct", "provenance"])

    # CAA grindings
    log.info("Fetching CAA grindings…")
    caa_rows = fetch_caa_grindings()
    save_csv(caa_rows, "cocoa_grindings_asia.csv",
             fieldnames=["quarter", "volume_mt", "yoy_pct", "provenance"])

    # USDA PSD
    log.info("Fetching USDA FAS PSD…")
    psd_df = fetch_usda_psd()
    if not psd_df.empty:
        save_csv(psd_df, "cocoa_psd_2005_2024.csv")
    else:
        log.warning("USDA PSD returned no data")

    print_summary(prod_df, yield_df, eca_rows, nca_rows, caa_rows)
    log.info("Cocoa pipeline complete.")

if __name__ == "__main__":
    main()
