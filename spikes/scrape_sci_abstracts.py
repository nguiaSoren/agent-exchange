"""Second-domain corpus for the F-N replication: real scientific abstracts from arXiv.

Claim-vs-abstract verification is the canonical scientific analogue of claim-vs-contract: a claim is
SUPPORTED iff the abstract states it (or it follows directly), UNSUPPORTED if it relies on outside
knowledge or scope the abstract does not state. We pull a handful of recent abstracts across many
arXiv categories (diverse domains, like the 27-domain EDGAR set) and write them in the same corpus
format the adaptive-attack harness consumes (``{"contracts": [text, ...]}``), plus a SOURCES file
citing each by arXiv ID + URL. Public-domain metadata; no model calls.

Out: data/eval/sci_abstracts_real.json (+ .meta.json) and data/eval/SOURCES_sci_abstracts.md.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
import xml.etree.ElementTree as ET

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT = os.path.join(_ROOT, "data", "eval", "sci_abstracts_real.json")
_META = os.path.join(_ROOT, "data", "eval", "sci_abstracts_real.meta.json")
_SRC = os.path.join(_ROOT, "data", "eval", "SOURCES_sci_abstracts.md")

_ATOM = "{http://www.w3.org/2005/Atom}"
# diverse domains: ML, NLP, neuroscience, optics, probability, econometrics, statistics,
# astrophysics, soft matter, signal processing, quant finance, nonlinear dynamics
_CATS = ["cs.LG", "cs.CL", "q-bio.NC", "physics.optics", "math.PR", "econ.EM",
         "stat.ME", "astro-ph.GA", "cond-mat.soft", "eess.SP", "q-fin.ST", "nlin.AO"]
_PER_CAT = 2


def _fetch(cat: str, n: int):
    url = (f"http://export.arxiv.org/api/query?search_query=cat:{cat}"
           f"&start=0&max_results={n}&sortBy=submittedDate&sortOrder=descending")
    req = urllib.request.Request(url, headers={"User-Agent": "fn-replication/1.0 (research)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        root = ET.fromstring(r.read())
    out = []
    for e in root.findall(f"{_ATOM}entry"):
        title = " ".join((e.findtext(f"{_ATOM}title") or "").split())
        summary = " ".join((e.findtext(f"{_ATOM}summary") or "").split())
        aid_url = (e.findtext(f"{_ATOM}id") or "").strip()
        aid = aid_url.rsplit("/", 1)[-1]
        if title and len(summary) > 200:  # substantive abstract
            out.append({"arxiv_id": aid, "url": aid_url, "category": cat, "title": title, "abstract": summary})
    return out


def main() -> None:
    docs, meta = [], []
    for cat in _CATS:
        try:
            got = _fetch(cat, _PER_CAT + 1)[:_PER_CAT]
        except Exception as ex:  # noqa: BLE001
            print(f"  [skip {cat}] {type(ex).__name__}: {ex}")
            got = []
        for g in got:
            # the "document" is the abstract with its title as a header (claim-verification target)
            doc = f"Title: {g['title']}\n\nAbstract: {g['abstract']}"
            docs.append(doc)
            meta.append({k: g[k] for k in ("arxiv_id", "url", "category", "title")})
            print(f"  {g['category']:14} {g['arxiv_id']:18} {g['title'][:60]}")
        time.sleep(3.1)  # arXiv API politeness

    json.dump({"contracts": docs}, open(_OUT, "w"), indent=2)
    json.dump({"n": len(docs), "categories": _CATS, "items": meta}, open(_META, "w"), indent=2)
    toks = [len(d.split()) for d in docs]
    med = sorted(toks)[len(toks) // 2] if toks else 0
    with open(_SRC, "w") as f:
        f.write("# Second-domain corpus: real arXiv abstracts (F-N replication)\n\n")
        f.write(f"{len(docs)} abstracts across {len(set(m['category'] for m in meta))} arXiv categories, "
                f"median ~{med} words. Public arXiv metadata, each citable by ID + URL.\n\n")
        f.write("| # | arXiv ID | category | title | URL |\n|---|---|---|---|---|\n")
        for i, m in enumerate(meta):
            f.write(f"| {i} | {m['arxiv_id']} | {m['category']} | {m['title'][:70]} | {m['url']} |\n")
    print(f"\n{len(docs)} abstracts → {_OUT}  (median ~{med} words)")
    print(f"sources → {_SRC}")


if __name__ == "__main__":
    main()
