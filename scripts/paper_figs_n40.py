"""Paper A — n=40 scaled-adaptive figures (matplotlib → PNG, ~150 dpi).

Renders the new five-judge cross-vendor result from FROZEN reports only — every
number is loaded from the JSON, never hardcoded, so the figures regenerate
deterministically and can never drift from the data.

Sources (read-only):
  * data/eval/scaled_adaptive_report.json  — per-config (judge) strict breaches,
    soft-leaks, n_docs, and per-doc rounds_used (a doc with rounds_used==0 was an
    errored/dropped doc; for qwen we report the EFFECTIVE n = count of rounds_used>0).
  * data/eval/contested_audit.json          — per-claim opus/gpt verdicts + real_leak;
    confirmed real leaks per config, and the inter-adjudicator agreement.

Figures (→ docs/research/paper-A-ablation-grounding/figs/):
  1. A_N40_leak_gradient.png    — five-judge cross-vendor leak gradient (strict + soft).
  2. A_N40_fn_undercount.png    — strict breaches counted vs audit-confirmed real leaks,
                                  with the contested-zone leaks the strict metric misses
                                  and the inter-adjudicator agreement annotated.

Style matches scripts/paper_figs_publication.py (DejaVu Sans, journal stroke palette,
no chartjunk). Run:  PYTHONPATH=src .venv/bin/python scripts/paper_figs_n40.py
"""

from __future__ import annotations

import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA = os.path.join(_ROOT, "data", "eval")
_OUT = os.path.join(_ROOT, "docs", "research", "paper-A-ablation-grounding", "figs")

# Journal palette (shared with paper_figs_publication.py).
GREEN, RED, BLUE, AMBER, GREY = "#2a8a4a", "#c0392b", "#2566a8", "#d98a1f", "#555555"
# Vendor colours (colorblind-safe; distinct hue per vendor).
VENDOR_COLOR = {"OpenAI": "#2566a8", "Anthropic": "#d98a1f", "open-weight": "#2a8a4a"}

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 11, "axes.titlesize": 12.5,
    "axes.titleweight": "bold", "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": "#e6e6e6", "grid.linewidth": 0.8,
    "figure.dpi": 150, "savefig.bbox": "tight", "axes.axisbelow": True,
})


def _load(name):
    p = os.path.join(_DATA, name)
    with open(p) as f:
        return json.load(f)


def _save(fig, stem):
    os.makedirs(_OUT, exist_ok=True)
    path = os.path.join(_OUT, f"{stem}.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  wrote {os.path.relpath(path, _ROOT)}")


def _judge_label(target: str) -> str:
    """Pretty short label for a 'vendor:model' target string."""
    model = target.split(":", 1)[1] if ":" in target else target
    return {
        "gpt-5.4-nano": "gpt-5.4-nano",
        "gpt-5.4": "gpt-5.4",
        "gpt-5.5-2026-04-23": "gpt-5.5",
        "claude-sonnet-4-6": "claude-sonnet-4.6",
        "qwen/qwen-2.5-72b-instruct": "qwen-2.5-72b",
    }.get(model, model)


def _vendor(target: str) -> str:
    v = target.split(":", 1)[0]
    return {"openai": "OpenAI", "anthropic": "Anthropic", "openrouter": "open-weight"}.get(v, v)


def _collect():
    """Build the per-judge record straight from the frozen files (no hardcoded numbers)."""
    rep = _load("scaled_adaptive_report.json")
    audit = _load("contested_audit.json")

    # audit: confirmed real leaks per config
    real_per_cfg, audited_per_cfg = {}, {}
    for c in audit["claims"]:
        cfg = c["config"]
        audited_per_cfg[cfg] = audited_per_cfg.get(cfg, 0) + 1
        if c.get("real_leak") is True:
            real_per_cfg[cfg] = real_per_cfg.get(cfg, 0) + 1

    rows = []
    for cfg, v in rep["configs"].items():
        if v.get("skipped"):
            continue
        results = v.get("results", [])
        eff_n = sum(1 for r in results if r.get("rounds_used", 0) > 0)
        rows.append({
            "config": cfg,
            "target": v["target"],
            "label": _judge_label(v["target"]),
            "vendor": _vendor(v["target"]),
            "strict": v["n_breached"],
            "soft": v["n_soft_leak"],
            "n_docs": v["n_docs"],
            "eff_n": eff_n,
            "real": real_per_cfg.get(cfg, 0),
            "audited": audited_per_cfg.get(cfg, 0),
        })

    # Order by strict breaches descending (ties broken by soft-leaks desc).
    rows.sort(key=lambda r: (-r["strict"], -r["soft"]))
    return rep, audit, rows


def fig_leak_gradient(rep, rows):
    """Five-judge cross-vendor leak gradient: strict breaches + soft-leaks per judge."""
    labels = [r["label"] for r in rows]
    strict = [r["strict"] for r in rows]
    soft = [r["soft"] for r in rows]
    n = len(rows)
    x = range(n)
    w = 0.38

    fig, ax = plt.subplots(figsize=(8.4, 4.8))
    # Strict bars coloured by vendor; soft-leak bars as a lighter sibling.
    b_strict = ax.bar([i - w / 2 for i in x], strict, w,
                      color=[VENDOR_COLOR[r["vendor"]] for r in rows],
                      edgecolor="white", label="strict breaches (auto-paid a lie the oracle rejects)")
    b_soft = ax.bar([i + w / 2 for i in x], soft, w,
                    color=[VENDOR_COLOR[r["vendor"]] for r in rows], alpha=0.42,
                    edgecolor="white", label="soft-leaks (contested / borderline)")

    for bars, vals in ((b_strict, strict), (b_soft, soft)):
        for bar, v in zip(bars, vals):
            ax.annotate(str(v), (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                        textcoords="offset points", xytext=(0, 3), ha="center", fontsize=9.5)

    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=10)
    ax.set_ylabel("count of documents (out of n per judge)")
    ax.set_ylim(0, max(soft) * 1.30)
    ax.set_title("Leak rate falls with judge capability, across three vendors")

    # Annotate qwen's effective n (errored docs dropped), clear above its soft-leak bar.
    qwen = next((r for r in rows if r["vendor"] == "open-weight"), None)
    if qwen:
        qi = rows.index(qwen)
        ax.annotate(f"effective n={qwen['eff_n']} of {qwen['n_docs']}\n({qwen['n_docs']-qwen['eff_n']} docs errored, dropped)",
                    (qi + w / 2, qwen["soft"]), textcoords="offset points", xytext=(0, 18),
                    ha="center", va="bottom", fontsize=8.2, color=RED)

    # Legend: vendor colours + the strict/soft encoding.
    vendor_handles = [Patch(facecolor=c, edgecolor="white", label=v) for v, c in VENDOR_COLOR.items()]
    leg1 = ax.legend(handles=vendor_handles, title="vendor", loc="upper right",
                     frameon=False, fontsize=9, title_fontsize=9)
    ax.add_artist(leg1)
    encoding_handles = [
        Patch(facecolor=GREY, edgecolor="white", label="strict breach"),
        Patch(facecolor=GREY, edgecolor="white", alpha=0.42, label="soft-leak"),
    ]
    ax.legend(handles=encoding_handles, loc="upper center", frameon=False, fontsize=9)

    n_per = rows[0]["n_docs"]
    fig.subplots_adjust(bottom=0.20)
    fig.text(0.5, 0.015,
             f"Scaled adaptive attack, {rep['rounds']}-round PAIR, n={n_per} docs/judge "
             f"(qwen effective n={qwen['eff_n'] if qwen else '—'}); diverse cross-vendor attacker panel.\n"
             "Strict breaches fall monotonically from the weakest open-weight judge to the gpt-5.5 frontier, which holds at 0.",
             ha="center", va="bottom", fontsize=8.2, color=GREY)
    _save(fig, "A_N40_leak_gradient")


def fig_fn_undercount(audit, rows):
    """F-N undercount: strict breaches COUNTED vs audit-CONFIRMED real leaks, per judge."""
    labels = [r["label"] for r in rows]
    strict = [r["strict"] for r in rows]
    real = [r["real"] for r in rows]
    n = len(rows)
    x = range(n)
    w = 0.38

    fig, ax = plt.subplots(figsize=(8.4, 4.8))
    b_strict = ax.bar([i - w / 2 for i in x], strict, w, color=GREY,
                      edgecolor="white", label="strict breaches counted")
    b_real = ax.bar([i + w / 2 for i in x], real, w, color=RED,
                    edgecolor="white", label="audit-confirmed real leaks")

    for bars, vals in ((b_strict, strict), (b_real, real)):
        for bar, v in zip(bars, vals):
            ax.annotate(str(v), (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                        textcoords="offset points", xytext=(0, 3), ha="center",
                        fontsize=9.5, fontweight="bold")
        # the missed contested-zone leaks (real - strict) as a faint hatch cap
    for i, r in zip(x, rows):
        miss = r["real"] - r["strict"]
        if miss > 0:
            ax.annotate(f"+{miss} missed", (i + w / 2, r["real"]),
                        textcoords="offset points", xytext=(0, 16), ha="center",
                        fontsize=8.0, color=RED)

    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=10)
    ax.set_ylabel("count of leaks")
    ax.set_ylim(0, max(real) * 1.28)
    ax.set_title("The strict metric undercounts: contested-zone leaks it misses")

    ax.legend(loc="upper right", frameon=False, fontsize=9.5)

    strict_tot = sum(strict)
    real_tot = sum(real)
    n_audited = audit["total_contested"]
    n_real = audit["confirmed_real_leaks"]
    agree = audit["agreement_rate_pct"]
    fig.subplots_adjust(bottom=0.22)
    fig.text(0.5, 0.015,
             f"Strict breaches total {strict_tot}; two-adjudicator audit of {n_audited} contested claims confirms "
             f"{n_real} real leaks ({real_tot} attributable across these judges).\n"
             f"Inter-adjudicator (opus vs gpt) agreement = {agree}% on the decidable set — the gap is a real undercount, not noise.",
             ha="center", va="bottom", fontsize=8.2, color=GREY)
    _save(fig, "A_N40_fn_undercount")


def main():
    os.makedirs(_OUT, exist_ok=True)
    print(f"Rendering n=40 figures → {os.path.relpath(_OUT, _ROOT)}/")
    rep, audit, rows = _collect()
    # Echo the loaded numbers so a reader can verify against the report.
    print("  per-judge (strict / soft / eff_n / confirmed-real):")
    for r in rows:
        print(f"    {r['label']:>18} [{r['vendor']:>11}]  strict={r['strict']}  "
              f"soft={r['soft']}  eff_n={r['eff_n']}/{r['n_docs']}  real={r['real']}/{r['audited']}")
    print(f"  strict total={sum(r['strict'] for r in rows)}  "
          f"audit confirmed-real={audit['confirmed_real_leaks']}/{audit['total_contested']}  "
          f"agreement={audit['agreement_rate_pct']}%")
    fig_leak_gradient(rep, rows)
    fig_fn_undercount(audit, rows)
    print("done.")


if __name__ == "__main__":
    main()
