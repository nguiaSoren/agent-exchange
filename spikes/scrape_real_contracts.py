"""Scrape REAL contracts from SEC EDGAR (material-contract exhibits, EX-10.x) across diverse
domains, for the judge-spine corpus. EDGAR filings are public-domain government records, so the
documents are real, varied, and clean to use.

Pipeline: EDGAR full-text search (efts.sec.gov JSON, with retry/backoff) -> build exhibit URLs
-> fetch HTML with crawl4ai -> markdown -> clean + title-anchored domain check + truncate ->
round-robin across domains -> save ``{"contracts":[...]}`` plus a provenance sidecar
(``*.meta.json``: domain, title, company, cik, file_type, url, verified) so every document is
citable and its domain label is auditable.

No LLM spend (web only). Writes a SEPARATE file; the frozen synthetic corpus is left untouched.
Env: CORPUS_N (default 40), PER_DOMAIN (EFTS candidates/domain, default 8),
     MAX_PER_DOMAIN (cap in final set, default 5), MAX_WORDS (default 2400, clears Sonnet 2048 cache min),
     CORPUS_OUT (default data/eval/long_contracts_real.json),
     SEC_UA (SEC requires a descriptive User-Agent with contact).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict, deque

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_UA = os.getenv("SEC_UA", "AgentExchange Research nguiasoren@gmail.com")

# Diverse contract domains -> a SIMPLE, robust EDGAR full-text query + the keyword(s) that must
# appear in the document's title/preamble for the domain label to be trusted (title-anchored).
DOMAINS: list[tuple[str, str, list[str]]] = [
    ("master_services", '"master services agreement"', ["master services"]),
    ("saas", '"software-as-a-service"', ["software-as-a-service", "software as a service", "saas"]),
    ("nda", '"non-disclosure agreement"', ["non-disclosure", "nondisclosure"]),
    ("software_license", '"software license agreement"', ["software license"]),
    ("employment", '"employment agreement"', ["employment"]),
    ("lease", '"lease agreement"', ["lease"]),
    ("credit", '"credit agreement"', ["credit agreement"]),
    ("loan", '"loan agreement"', ["loan"]),
    ("supply", '"supply agreement"', ["supply"]),
    ("distribution", '"distribution agreement"', ["distribution"]),
    ("consulting", '"consulting agreement"', ["consulting"]),
    ("manufacturing", '"manufacturing agreement"', ["manufacturing"]),
    ("patent_license", '"patent license agreement"', ["patent license"]),
    ("trademark_license", '"trademark license agreement"', ["trademark license"]),
    ("severance", '"severance agreement"', ["severance"]),
    ("indemnification", '"indemnification agreement"', ["indemnification"]),
    ("security_agreement", '"security agreement"', ["security agreement"]),
    ("asset_purchase", '"asset purchase agreement"', ["asset purchase"]),
    ("stock_purchase", '"stock purchase agreement"', ["stock purchase"]),
    ("merger", '"merger agreement"', ["merger"]),
    ("partnership", '"limited partnership agreement"', ["partnership"]),
    ("joint_venture", '"joint venture agreement"', ["joint venture"]),
    ("franchise", '"franchise agreement"', ["franchise"]),
    ("settlement", '"settlement agreement"', ["settlement"]),
    ("underwriting", '"underwriting agreement"', ["underwriting"]),
    ("registration_rights", '"registration rights agreement"', ["registration rights"]),
    ("escrow", '"escrow agreement"', ["escrow"]),
    ("guaranty", '"guaranty agreement"', ["guaranty", "guarantee"]),
]


def _efts(query: str, n: int, tries: int = 4) -> list[dict]:
    """EDGAR full-text search -> up to n EX-10.x exhibit candidates, with retry/backoff on 5xx."""
    url = "https://efts.sec.gov/LATEST/search-index?q=" + urllib.parse.quote(query)
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.load(r)
            break
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            last = e
            time.sleep(1.0 * (2 ** attempt))  # 1s, 2s, 4s, 8s
    else:
        raise last if last else RuntimeError("efts failed")
    out: list[dict] = []
    for h in d.get("hits", {}).get("hits", []):
        s = h.get("_source", {})
        ft = s.get("file_type") or ""
        if not ft.startswith("EX-10"):
            continue
        _id = h.get("_id", "")
        if ":" not in _id:
            continue
        adsh, fname = _id.split(":", 1)
        ciks = s.get("ciks") or []
        if not ciks or not fname.lower().endswith((".htm", ".html", ".txt")):
            continue
        cik = str(int(ciks[0]))
        out.append({
            "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{adsh.replace('-', '')}/{fname}",
            "company": (s.get("display_names") or [""])[0],
            "cik": cik,
            "file_type": ft,
            "adsh": adsh,
        })
        if len(out) >= n:
            break
    return out


def _title(md: str) -> str:
    m = re.search(r"([A-Z][A-Z0-9 &,'\-\.]{6,90}AGREEMENT)", md[:1500])
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def _clean(md: str, max_words: int) -> str:
    md = re.sub(r"\n{3,}", "\n\n", md or "").strip()
    keep = [
        ln for ln in md.splitlines()
        if not re.match(r"^\s*(Exhibit\s|EX-10|Table of Contents|Page \d+\b|\[.*\]\(.*\)\s*$)", ln, re.I)
    ]
    md = "\n".join(keep).strip()
    words = md.split()
    return " ".join(words[:max_words]) if len(words) > max_words else md


async def main() -> None:
    n = int(os.getenv("CORPUS_N", "40"))
    per = int(os.getenv("PER_DOMAIN", "8"))
    cap = int(os.getenv("MAX_PER_DOMAIN", "2"))
    max_words = int(os.getenv("MAX_WORDS", "2400"))  # ~3200 tok: clears Sonnet's ~2048 cache minimum so the weak/mid oracle caches too
    out = os.getenv("CORPUS_OUT") or os.path.join(_ROOT, "data", "eval", "long_contracts_real.json")
    meta_path = out.replace(".json", ".meta.json")

    def _flush() -> None:
        """Persist after EVERY fetch so source URLs survive a mid-run crash."""
        with open(out, "w", encoding="utf-8") as fh:
            json.dump({"contracts": contracts}, fh, ensure_ascii=False)
        with open(meta_path, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2, ensure_ascii=False)

    # 1) gather candidates per domain (with retry), keep them bucketed for round-robin spread.
    keymap = {d: kws for d, _, kws in DOMAINS}
    bydom: dict[str, deque] = defaultdict(deque)
    for label, q, _kws in DOMAINS:
        try:
            hits = _efts(q, n=per)
        except Exception as e:  # noqa: BLE001
            print(f"[efts {label}] giving up: {e}")
            continue
        for h in hits:
            h["domain"] = label
            bydom[label].append(h)
        print(f"[efts {label}] {len(hits)} candidates")
        time.sleep(0.4)  # SEC politeness
    total_cand = sum(len(v) for v in bydom.values())
    print(f"{total_cand} candidates across {len([d for d in bydom if bydom[d]])} domains; target n={n}")

    # 2) fetch round-robin across domains, title-anchored verify, dedup, per-domain cap.
    contracts: list[str] = []
    meta: list[dict] = []
    seen_urls: set[str] = set()
    seen_companies: set[str] = set()
    counts: dict[str, int] = defaultdict(int)
    order = [d for d, _, _ in DOMAINS if bydom[d]]
    browser = BrowserConfig(user_agent=_UA, headless=True, verbose=False)
    cfg = CrawlerRunConfig(page_timeout=45000, verbose=False)
    async with AsyncWebCrawler(config=browser) as crawler:
        while len(contracts) < n and any(bydom[d] for d in order):
            for d in order:
                if len(contracts) >= n:
                    break
                if counts[d] >= cap or not bydom[d]:
                    continue
                c = bydom[d].popleft()
                if c["url"] in seen_urls or c["company"] in seen_companies:
                    continue  # dedup by URL and by company (40 distinct companies → more diverse)
                seen_urls.add(c["url"])
                seen_companies.add(c["company"])
                try:
                    res = await crawler.arun(url=c["url"], config=cfg)
                    m = res.markdown
                    md = getattr(m, "raw_markdown", None) or (m if isinstance(m, str) else str(m))
                except Exception as e:  # noqa: BLE001
                    print(f"[fetch fail] {c['url']}: {e}")
                    continue
                title = _title(md)
                txt = _clean(md, max_words)
                if len(txt.split()) < 200 or txt in contracts:
                    continue
                head = txt[:1200].lower()
                verified = any(k in head for k in keymap.get(d, []))
                contracts.append(txt)
                meta.append({
                    "domain": d, "title": title, "company": c["company"], "cik": c["cik"],
                    "file_type": c["file_type"], "url": c["url"], "verified_domain": verified,
                })
                flag = "ok " if verified else "ok?"
                print(f"[{flag} {len(contracts):>2}/{n}] {d:16} {len(txt.split()):>4}w  {title[:46] or c['company'][:46]}")
                _flush()  # source URL persisted immediately, before the next fetch
                time.sleep(0.4)

    _flush()
    # Paper-ready citation list of every source (SEC EDGAR is public-domain).
    src_path = os.path.join(os.path.dirname(out), "SOURCES_real_contracts.md")
    with open(src_path, "w", encoding="utf-8") as f:
        f.write("# Real-contract corpus — sources (SEC EDGAR EX-10 exhibits, public-domain filings)\n\n")
        for i, mm in enumerate(meta, 1):
            tag = "" if mm["verified_domain"] else " _(domain unverified)_"
            f.write(f"{i}. **{mm['domain']}**{tag} — {mm.get('title') or mm['company']} "
                    f"({mm['company']}, {mm['file_type']}). <{mm['url']}>\n")
    print(f"Citations -> {src_path}")
    nver = sum(1 for m in meta if m["verified_domain"])
    ndom = len({m["domain"] for m in meta})
    print(f"\nWrote {len(contracts)} real contracts ({nver} title-verified) across {ndom} domains -> {out}")
    print(f"Provenance (sources + titles) -> {meta_path}")
    if len(contracts) >= 4:
        print(f"Pilot:  SCALED_CONTRACTS={out} SCALED_CONFIGS=weak,mid,frontier .venv/bin/python spikes/scaled_adaptive_run.py")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nAborted.")
