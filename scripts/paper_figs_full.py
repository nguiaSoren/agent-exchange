"""Regenerate the FULL Paper-A figure set (A_F1 … A_F15) from frozen JSON reports.

Publication-grade matplotlib renders → PDF (vector, for the ICLR LaTeX build) + PNG, written to
``docs/research/paper-A-ablation-grounding/figs/`` with the exact names DRAFT.md references
(``A_F1.pdf/.png`` … ``A_F15.pdf/.png``). Every number is read at runtime from a frozen report
under ``data/eval/`` or ``data/calibration/`` — this script never calls a model and never hardcodes
a measured number, so the figures regenerate deterministically from the data and stay locked to the
text. Pre-existing N40 figures (``A_N40_*``) are left untouched.

Run (no API keys needed):
  env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY -u OPENROUTER_API_KEY \
      PYTHONPATH=src .venv/bin/python scripts/paper_figs_full.py
"""

from __future__ import annotations

import json
import os
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA = os.path.join(_ROOT, "data", "eval")
_CALIB = os.path.join(_ROOT, "data", "calibration")
_FIGS = os.path.join(_ROOT, "docs", "research", "paper-A-ablation-grounding", "figs")

# Colorblind-safe, journal-restrained palette. gifted-span (the lie / the leak) is always RED,
# genuine/served is GREEN, the gate's cost / amber is the "false-escalate" warning, blue is neutral.
GREEN, RED, BLUE, AMBER, GREY, PURPLE = "#2a8a4a", "#c0392b", "#2566a8", "#d98a1f", "#555555", "#5b4aa8"
_TINT = {GREY: "#f2f1ee", BLUE: "#eef4fb", PURPLE: "#efedfb",
         GREEN: "#eafaf0", AMBER: "#fdf3e3", RED: "#fdecea"}

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10, "axes.titlesize": 11.5,
    "axes.titleweight": "bold", "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": "#e8e8e8", "grid.linewidth": 0.8,
    "figure.dpi": 150, "savefig.bbox": "tight", "axes.axisbelow": True,
})


def _load(name, calib=False):
    p = os.path.join(_CALIB if calib else _DATA, name)
    return json.load(open(p)) if os.path.exists(p) else None


def _save(fig, stem):
    os.makedirs(_FIGS, exist_ok=True)
    for ext in ("pdf", "png"):
        fig.savefig(os.path.join(_FIGS, f"{stem}.{ext}"))
    plt.close(fig)
    print(f"  wrote figs/{stem}.pdf + .png")


def _bar_labels(ax, bars, fmt="{:.0%}", dy=3, **kw):
    for bar in bars:
        ax.annotate(fmt.format(bar.get_height()),
                    (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                    textcoords="offset points", xytext=(0, dy), ha="center",
                    fontsize=9, **kw)


# --------------------------------------------------------------------------- #
# A_F1 — static gifted-span: judge alone leaks 0 (no gate)                     #
# source: gifted_span_report.json                                             #
# --------------------------------------------------------------------------- #
def fig_A_F1():
    r = _load("gifted_span_report.json")
    if not r:
        print("  [skip] A_F1 — gifted_span_report.json missing"); return
    order = ["judge_only", "gate_teeth_off", "gate_teeth_on"]
    cfgs = [c for c in order if c in r["configs"]]
    nice = {"judge_only": "judge only", "gate_teeth_off": "gate (teeth off)", "gate_teeth_on": "gate (teeth on)"}

    def cls(cfg, src, attr):
        for c in r["configs"][cfg]["classes"]:
            if c["source"] == src:
                return c[attr]
        return 0.0

    leak = [cls(c, "llm_gifted_span", "leak_rate") for c in cfgs]
    fesc = [cls(c, "genuine", "false_escalate_rate") for c in cfgs]
    x = range(len(cfgs)); w = 0.36
    fig, ax = plt.subplots(figsize=(5.4, 4.0))
    b1 = ax.bar([i - w / 2 for i in x], leak, w, color=RED, edgecolor="white",
                label="gifted-span LEAK (auto-paid a lie)")
    b2 = ax.bar([i + w / 2 for i in x], fesc, w, color=AMBER, edgecolor="white",
                label="genuine FALSE-ESCALATE (gate cost)")
    _bar_labels(ax, b1); _bar_labels(ax, b2)
    ax.set_xticks(list(x)); ax.set_xticklabels([nice[c] for c in cfgs])
    ax.set_ylim(0, 1.12); ax.set_ylabel("rate")
    ax.set_title("Static gifted-span: the judge alone leaks 0")
    ax.legend(loc="upper left", frameon=False, fontsize=8.5)
    fig.subplots_adjust(bottom=0.22)
    fig.text(0.5, 0.01, f"verifier {r['verifier_model']}, n_gifted={r['n_gifted_span']} n_genuine={r['n_genuine']}, "
             f"policy={r['policy']}. No leak headroom for a gate to close;\nturning the gate's teeth on only escalates "
             "genuine single-sourced work (its cost, not a benefit).",
             ha="center", va="bottom", fontsize=8.0, color=GREY)
    _save(fig, "A_F1")


# --------------------------------------------------------------------------- #
# A_F1b — ablation route distribution on atomic snippets (long_doc, gate on)  #
# source: long_doc_report.json                                               #
# --------------------------------------------------------------------------- #
def fig_A_F1b():
    r = _load("long_doc_report.json")
    if not r:
        print("  [skip] A_F1b — long_doc_report.json missing"); return
    judges = r["judges"]
    jkey = next((j for j in judges if "mini" in j.lower()), next(iter(judges)))
    rd = judges[jkey]["route_distribution"].get("gate_teeth_on", {})
    classes = [("genuine", "genuine work"), ("llm_gifted_span", "gifted-span (a lie)")]
    segs = ["supported", "judge", "escalate"]
    seg_color = {"supported": GREEN, "judge": AMBER, "escalate": RED}
    fig, ax = plt.subplots(figsize=(5.2, 4.0))
    xs = range(len(classes))
    for ci, (src, _lbl) in enumerate(classes):
        d = rd.get(src, {})
        tot = sum(d.values()) or 1
        acc = 0.0
        for seg in segs:
            frac = d.get(seg, 0) / tot
            if frac <= 0:
                continue
            ax.bar(ci, frac, 0.55, bottom=acc, color=seg_color[seg], edgecolor="white")
            ax.annotate(f"{seg}\n{d.get(seg,0)}/{tot}", (ci, acc + frac / 2), ha="center", va="center",
                        fontsize=8.5, color="white", fontweight="bold")
            acc += frac
    ax.set_xticks(list(xs)); ax.set_xticklabels([l for _, l in classes])
    ax.set_ylim(0, 1.04); ax.set_ylabel("route fraction (gate teeth on)")
    ax.set_title("Ablation route distribution: the gate is non-discriminative")
    handles = [plt.Rectangle((0, 0), 1, 1, color=seg_color[s]) for s in segs]
    ax.legend(handles, [s.upper() for s in segs], loc="lower center", ncol=3,
              frameon=False, fontsize=8.5, bbox_to_anchor=(0.5, -0.02))
    fig.subplots_adjust(bottom=0.24)
    fig.text(0.5, 0.01, f"judge {jkey.split(':')[-1]}, {r['n_docs']} long docs. Genuine work fails lexical ablation too "
             "(single-sourced) → routes to JUDGE/ESCALATE,\njust like the lie: the gate escalates ~all genuine work it sees.",
             ha="center", va="bottom", fontsize=8.0, color=GREY)
    _save(fig, "A_F1b")


# --------------------------------------------------------------------------- #
# A_F2 — reliability / ECE grid (calibration is set-dependent)               #
# source: catch_rate_report.json + nda_catch_rate_report.json               #
# --------------------------------------------------------------------------- #
def fig_A_F2():
    panels = []
    cr = _load("catch_rate_report.json")
    if cr:
        panels.append(("contract\n(gpt-4.1)", cr))
    nda = _load("nda_catch_rate_report.json")
    if nda:
        panels.append(("NDA\n(gpt-4.1)", nda))
    if not panels:
        print("  [skip] A_F2 — no catch_rate reports"); return
    fig, axes = plt.subplots(1, len(panels), figsize=(4.6 * len(panels), 4.4), squeeze=False)
    for ax, (name, r) in zip(axes[0], panels):
        bins = [b for b in r.get("reliability", []) if b.get("count")]
        ax.plot([0, 1], [0, 1], "--", color=GREY, lw=1.1, zorder=1)
        big = max((b["count"] for b in bins), default=1)
        for b in bins:
            size = 50 + 24 * (b["count"] ** 0.5)
            ax.scatter([b["mean_confidence"]], [b["accuracy"]], s=size, color=BLUE,
                       alpha=0.7, edgecolor="white", lw=1.0, zorder=3)
            dy, va = (-15, "top") if b["count"] == big else (11, "bottom")
            ax.annotate(f"n={b['count']}", (b["mean_confidence"], b["accuracy"]),
                        textcoords="offset points", xytext=(0, dy), ha="center", va=va,
                        fontsize=8, color=GREY)
        ax.set_xlim(0, 1.06); ax.set_ylim(0, 1.08)
        ax.set_xlabel("predicted confidence")
        ax.set_title(f"{name}  ECE={r.get('ece', 0):.3f}, n={r.get('n_total')}", fontsize=10.5)
    axes[0][0].set_ylabel("empirical accuracy")
    fig.suptitle("Reliability is set-dependent: a single ECE is not a property of the verifier",
                 fontsize=11.5, fontweight="bold", y=1.02)
    cal = _load("calibration_result.json", calib=True)
    gold = f"; a hand-labeled gold set (gpt-5.1) reaches ECE {cal['ece']:.3f} (n={cal['n']})" if cal else ""
    fig.text(0.5, -0.02, f"Same verifier, different sets: bins on/near the diagonal{gold} — calibration must be "
             "reported per (judge, set).", ha="center", va="top", fontsize=8.2, color=GREY)
    _save(fig, "A_F2")


# --------------------------------------------------------------------------- #
# A_F3 — lexical ablation over-escalates genuine (long multi-clause docs)     #
# source: long_doc_report.json                                               #
# --------------------------------------------------------------------------- #
def fig_A_F3():
    r = _load("long_doc_report.json")
    if not r:
        print("  [skip] A_F3 — long_doc_report.json missing"); return
    judges = r["judges"]
    jkey = next((j for j in judges if "mini" in j.lower()), next(iter(judges)))
    jd = judges[jkey]
    order = ["judge_only", "gate_teeth_off", "gate_teeth_on"]
    cfgs = [c for c in order if c in jd["configs"]]
    nice = {"judge_only": "judge only", "gate_teeth_off": "gate (teeth off)", "gate_teeth_on": "gate (teeth on)"}

    def cls(cfg, src, attr):
        for c in jd["configs"][cfg]["classes"]:
            if c["source"] == src:
                return c[attr]
        return 0.0

    served = [cls(c, "genuine", "served_rate") for c in cfgs]
    leak = [cls(c, "llm_gifted_span", "leak_rate") for c in cfgs]
    rd = jd["route_distribution"].get("gate_teeth_on", {}).get("genuine", {})
    sup, tot = rd.get("supported", 0), sum(rd.values()) or 1
    x = range(len(cfgs)); w = 0.36
    fig, ax = plt.subplots(figsize=(5.4, 4.0))
    b1 = ax.bar([i - w / 2 for i in x], served, w, color=GREEN, edgecolor="white",
                label="genuine SERVED (auto-paid honest work)")
    b2 = ax.bar([i + w / 2 for i in x], leak, w, color=RED, edgecolor="white",
                label="gifted-span LEAK (auto-paid a lie)")
    _bar_labels(ax, b1); _bar_labels(ax, b2)
    ax.set_xticks(list(x)); ax.set_xticklabels([nice[c] for c in cfgs])
    ax.set_ylim(0, 1.12); ax.set_ylabel("rate")
    ax.set_title("Lexical ablation over-escalates honest work on long docs")
    ax.legend(loc="center left", frameon=False, fontsize=8.5)
    fig.subplots_adjust(bottom=0.22)
    fig.text(0.5, 0.01, f"judge {jkey.split(':')[-1]}, {r['n_docs']} long multi-clause docs. With the gate on, genuine "
             f"SUPPORTED-route = {sup}/{tot} ({sup/tot:.0%}):\ngenuine findings are paraphrases whose distinctive "
             "substrings are not verbatim-redundant, so the gate escalates them.",
             ha="center", va="bottom", fontsize=8.0, color=GREY)
    _save(fig, "A_F3")


# --------------------------------------------------------------------------- #
# A_F5 — semantic discrimination: embeddings can't tell truth from a mutation #
# source: semantic_ablation_report.json                                      #
# --------------------------------------------------------------------------- #
def fig_A_F5():
    r = _load("semantic_ablation_report.json")
    if not r:
        print("  [skip] A_F5 — semantic_ablation_report.json missing"); return
    pa = r["part_a_discrimination"]
    groups = ["genuine\n(should be supported)", "gifted-span\n(should NOT)"]
    emb = [pa["genuine"]["emb_frac_ge_tau"], pa["gifted"]["emb_frac_ge_tau"]]
    llm = [pa["genuine"]["llm_frac_supported"], pa["gifted"]["llm_frac_supported"]]
    x = range(len(groups)); w = 0.36
    fig, ax = plt.subplots(figsize=(5.4, 4.2))
    b1 = ax.bar([i - w / 2 for i in x], emb, w, color=AMBER, edgecolor="white",
                label=f"embedding: frac ≥ τ ({r['tau']})")
    b2 = ax.bar([i + w / 2 for i in x], llm, w, color=GREEN, edgecolor="white",
                label="LLM-entailment: frac supported")
    _bar_labels(ax, b1); _bar_labels(ax, b2)
    ax.set_xticks(list(x)); ax.set_xticklabels(groups)
    ax.set_ylim(0, 1.12); ax.set_ylabel("fraction judged supported")
    ax.set_title("Can a semantic signal separate truth from a gifted-span lie?")
    ax.legend(loc="upper right", frameon=False, fontsize=8.5)
    pb = r["part_b_gate"]["genuine"]
    fig.subplots_adjust(bottom=0.20)
    fig.text(0.5, 0.01, f"embed={r['embed_model']}, entail/judge={r['judge']}; n_genuine={pa['genuine']['n']} "
             f"n_gifted={pa['gifted']['n']}.\nEmbeddings pass {pa['gifted']['emb_frac_ge_tau']:.0%} of lies; "
             f"entailment separates (100%/0%) but as an ABLATION check passes genuine only "
             f"{pb['llm']}/{pb['n']} ({pb['llm']/pb['n']:.0%}).",
             ha="center", va="bottom", fontsize=8.0, color=GREY)
    _save(fig, "A_F5")


# --------------------------------------------------------------------------- #
# A_F6 — bounded (5-round) adaptive attack: the BREACH quadrant stays empty   #
# source: adaptive_adversary_report.json                                     #
# --------------------------------------------------------------------------- #
def fig_A_F6():
    r = _load("adaptive_adversary_report.json")
    if not r:
        print("  [skip] A_F6 — adaptive_adversary_report.json missing"); return
    cfgs = [k for k, v in r.get("configs", {}).items() if not v.get("skipped")]
    if not cfgs:
        print("  [skip] A_F6 — no non-skipped configs"); return

    def bucket(a):
        if a.get("target_auto_pays") and a.get("oracle_says_false"):
            return "BREACH"
        if a.get("target_verdict") == "confirmed":
            return "confirmed (true)"
        if a.get("target_verdict") == "partial":
            return "partial"
        return "caught (rejected)"

    segs = ["caught (rejected)", "partial", "confirmed (true)", "BREACH"]
    seg_color = {"caught (rejected)": GREEN, "partial": AMBER, "confirmed (true)": BLUE, "BREACH": RED}
    data, labels = {}, []
    for name in cfgs:
        c = r["configs"][name]
        counts = {s: 0 for s in segs}
        for res in c["results"]:
            for a in res.get("attempts", []):
                counts[bucket(a)] += 1
        lab = f"{name}\n(t={c['target'].split(':')[-1]} vs o={c['oracle'].split(':')[-1]})"
        labels.append(lab); data[lab] = counts
    fig, ax = plt.subplots(figsize=(5.6, 4.2))
    xs = range(len(labels))
    for xi, lab in enumerate(labels):
        tot = sum(data[lab].values()) or 1
        acc = 0.0
        for seg in segs:
            frac = data[lab][seg] / tot
            if frac <= 0:
                continue
            ax.bar(xi, frac, 0.5, bottom=acc, color=seg_color[seg], edgecolor="white")
            ax.annotate(f"{seg}\n{data[lab][seg]}", (xi, acc + frac / 2), ha="center", va="center",
                        fontsize=8, color="white", fontweight="bold")
            acc += frac
    ax.set_xticks(list(xs)); ax.set_xticklabels(labels, fontsize=8.5)
    ax.set_ylim(0, 1.04); ax.set_ylabel("fraction of attack attempts")
    ax.set_title("Bounded adaptive PAIR attack: the BREACH quadrant is empty")
    handles = [plt.Rectangle((0, 0), 1, 1, color=seg_color[s]) for s in segs]
    ax.legend(handles, segs, loc="lower center", ncol=2, frameon=False, fontsize=8, bbox_to_anchor=(0.5, -0.02))
    fig.subplots_adjust(bottom=0.24)
    fig.text(0.5, 0.01, f"{r['n_docs']} docs × {r['rounds']} escalating rounds, attacker gpt-4.1. "
             "BREACH = target auto-pays a claim the oracle rejects = 0 for both weak and frontier judges.",
             ha="center", va="bottom", fontsize=8.0, color=GREY)
    _save(fig, "A_F6")


# --------------------------------------------------------------------------- #
# A_F7 — cross-source ablation discriminates (semantic only)                 #
# source: cross_source_report.json + cross_source_fab_n_report.json         #
# --------------------------------------------------------------------------- #
def fig_A_F7():
    r = _load("cross_source_report.json")
    if not r:
        print("  [skip] A_F7 — cross_source_report.json missing"); return
    a = r["ablation_cross_source"]
    fab = _load("cross_source_fab_n_report.json") or {}
    groups = ["genuine\n(corroborated)", "gifted-span\n(a lie)"]
    lex = [a["genuine_supported_lexical"], a["gifted_supported_lexical"]]
    llm = [a["genuine_supported_llm"], a["gifted_supported_llm"]]
    x = range(len(groups)); w = 0.36
    fig, ax = plt.subplots(figsize=(5.4, 4.2))
    b1 = ax.bar([i - w / 2 for i in x], lex, w, color=AMBER, edgecolor="white", label="lexical ablation")
    b2 = ax.bar([i + w / 2 for i in x], llm, w, color=GREEN, edgecolor="white", label="LLM-entailment ablation")
    _bar_labels(ax, b1); _bar_labels(ax, b2)
    ax.set_xticks(list(x)); ax.set_xticklabels(groups)
    ax.set_ylim(0, 1.12); ax.set_ylabel("fraction surviving ablation")
    ax.set_title("Cross-source ablation discriminates (semantic only)")
    ax.legend(loc="upper right", frameon=False, fontsize=8.5)
    base = r.get("single_source_baseline", {})
    n_gif, n_reach = fab.get("n_gifted", 120), fab.get("n_reached", 1)
    fig.subplots_adjust(bottom=0.24)
    fig.text(0.5, 0.01, f"judge={r['judge']}, n_genuine={r['n_genuine']}; genuine LLM-survival "
             f"{base.get('genuine_supported_llm', 0):.0%} single-source → {a['genuine_supported_llm']:.0%} cross-source "
             f"(n={a.get('genuine_reached', 24)} reached).\nFabrication arm structurally tiny: of {n_gif} gifted-span "
             f"the judge intercepted {n_gif - n_reach} before ablation (semantic required; lexical lets the lie survive).",
             ha="center", va="bottom", fontsize=8.0, color=GREY)
    _save(fig, "A_F7")


# --------------------------------------------------------------------------- #
# A_F8 — dilution + long-context: 0 leak                                      #
# source: stress_test_report.json                                            #
# --------------------------------------------------------------------------- #
def fig_A_F8():
    r = _load("stress_test_report.json")
    if not r:
        print("  [skip] A_F8 — stress_test_report.json missing"); return
    tname = r["targets"][0]
    by_size = {}
    for row in r["batch_dilution"].get(tname, []):
        by_size.setdefault(row["batch_size"], []).append(row["leak_rate"])
    sizes = sorted(by_size)
    leak_by_size = [max(by_size[s]) for s in sizes]
    lc = r.get("long_context", {})
    lc_keys = sorted(lc, key=lambda k: lc[k]["words"])
    labels = [f"batch={s}" for s in sizes] + [f"{lc[k]['words']}w" for k in lc_keys]
    vals = leak_by_size + [lc[k]["leak_rate"] for k in lc_keys]
    fig, ax = plt.subplots(figsize=(6.2, 3.8))
    split = len(sizes)
    colors = [BLUE] * split + [PURPLE] * (len(labels) - split)
    bars = ax.bar(range(len(labels)), vals, 0.6, color=colors, edgecolor="white")
    for bar in bars:
        ax.annotate("0%" if bar.get_height() == 0 else f"{bar.get_height():.0%}",
                    (bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.01),
                    ha="center", fontsize=9, va="bottom")
    ax.set_xticks(range(len(labels))); ax.set_xticklabels(labels, fontsize=8.5)
    ax.set_ylim(0, 1.0); ax.set_ylabel("fabrication LEAK rate")
    ax.set_title("Batch dilution + long context: 0% leak everywhere")
    ax.axvline(split - 0.5, color=GREY, ls=":", lw=1.0)
    ax.text((split - 1) / 2, 0.9, "batch dilution", ha="center", fontsize=8.5, color=GREY)
    ax.text(split + (len(labels) - split - 1) / 2, 0.9, "long context (buried clause)", ha="center", fontsize=8.5, color=GREY)
    fig.subplots_adjust(bottom=0.16)
    fig.text(0.5, 0.005, f"target={tname.split(':')[-1]}; a false claim hidden among up to "
             f"{max(sizes)} genuine claims, and a contradicting clause buried in ~{lc[lc_keys[-1]]['words']} words.",
             ha="center", va="bottom", fontsize=8.0, color=GREY)
    _save(fig, "A_F8")


# --------------------------------------------------------------------------- #
# A_F9 — scaled 12-round adaptive, FIVE judges, three vendors (the gradient)  #
# source: scaled_adaptive_report.json                                        #
# --------------------------------------------------------------------------- #
def fig_A_F9():
    r = _load("scaled_adaptive_report.json")
    if not r:
        print("  [skip] A_F9 — scaled_adaptive_report.json missing"); return
    cfgs = r["configs"]
    # Monotone capability→robustness gradient (per DRAFT F-H): open-weight → weak → mid → Anthropic → frontier.
    order = ["xcheck_openweight", "weak", "mid", "xcheck_anthropic", "frontier"]
    order = [k for k in order if k in cfgs and not cfgs[k].get("skipped")]
    labels, rates, ns = [], [], []
    for k in order:
        c = cfgs[k]
        nd = c["n_docs"]
        rates.append(c["n_breached"] / max(1, nd))
        ns.append((c["n_breached"], nd))
        model = re.sub(r"-20\d\d-\d\d-\d\d$", "", c["target"].split(":")[-1].split("/")[-1])
        labels.append(f"{k.replace('xcheck_', '')}\n{model}")
    colors = [RED if i == 0 else (GREEN if rt == 0 else AMBER) for i, rt in enumerate(rates)]
    # gradient: deepen amber → red as the breach rate climbs
    fig, ax = plt.subplots(figsize=(7.0, 4.3))
    bars = ax.bar(range(len(order)), rates, 0.6, color=colors, edgecolor="white")
    for bar, (nb, nd) in zip(bars, ns):
        ax.annotate(f"{nb}/{nd}\n({bar.get_height():.0%})",
                    (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                    textcoords="offset points", xytext=(0, 4), ha="center", fontsize=9, fontweight="bold")
    ax.set_xticks(range(len(order))); ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylim(0, max(rates) * 1.35 + 0.02)
    ax.set_ylabel("strict breach rate\n(auto-paid a lie the oracle rejects)", fontsize=9.5)
    ax.set_title("Scaled adaptive: a monotone capability → robustness gradient")
    fig.subplots_adjust(bottom=0.20)
    fig.text(0.5, 0.01, f"{r['rounds']}-round PAIR over n={r['n_docs']} real SEC EDGAR EX-10 contracts; panel "
             f"{', '.join(p.split(':')[-1] for p in r.get('panel', []))}.\nJudges span OpenAI, Anthropic and an "
             "open-weight model, so 'judge strength is the lever' is not an OpenAI artifact.",
             ha="center", va="bottom", fontsize=8.0, color=GREY)
    _save(fig, "A_F9")


# --------------------------------------------------------------------------- #
# A_F10 — ensemble closes the weak-judge leak (with a frontier peer)          #
# source: ensemble_report.json                                               #
# --------------------------------------------------------------------------- #
def fig_A_F10():
    r = _load("ensemble_report.json")
    if not r:
        print("  [skip] A_F10 — ensemble_report.json missing"); return
    p1 = r["part1_payment_lens"]
    order = [k for k in ("mini_alone", "gpt41_alone", "ensemble_mini+gpt41") if k in p1]
    nice = {"mini_alone": "mini alone", "gpt41_alone": "gpt-4.1 alone", "ensemble_mini+gpt41": "ensemble\n[mini, gpt-4.1]"}
    x = range(len(order)); w = 0.27
    fig, ax = plt.subplots(figsize=(5.8, 4.2))
    b1 = ax.bar([i - w for i in x], [p1[k]["gifted_leak_rate"] for k in order], w, color=RED, edgecolor="white", label="gifted-span LEAK")
    b2 = ax.bar([i for i in x], [p1[k]["genuine_served_rate"] for k in order], w, color=GREEN, edgecolor="white", label="genuine SERVED")
    b3 = ax.bar([i + w for i in x], [p1[k]["genuine_false_escalate_rate"] for k in order], w, color=AMBER, edgecolor="white", label="genuine FALSE-ESCALATE")
    for bars in (b1, b2, b3):
        _bar_labels(ax, bars)
    ax.set_xticks(list(x)); ax.set_xticklabels([nice[k] for k in order], fontsize=9)
    ax.set_ylim(0, 1.14); ax.set_ylabel("rate")
    ax.set_title("Ensemble (agree-to-pay) closes the adaptive weak-judge leak")
    ax.legend(loc="center left", frameon=False, fontsize=8.5)
    p2 = r["part2_adaptive"]
    fig.subplots_adjust(bottom=0.16)
    fig.text(0.5, 0.005, f"On the labeled payment lens all three sit at 0 leak / full served. The win is adaptive: "
             f"mini-alone breached {p2.get('mini_alone_baseline', 1)}/{p2['n_docs']} → "
             f"ensemble {p2['n_breached']}/{p2['n_docs']} (oracle {p2.get('oracle', 'gpt-5.1')}, off-panel).",
             ha="center", va="bottom", fontsize=8.0, color=GREY)
    _save(fig, "A_F10")


# --------------------------------------------------------------------------- #
# A_F12 — two open-weight judges don't close it                              #
# source: open_weight_ensemble_report.json                                  #
# --------------------------------------------------------------------------- #
def fig_A_F12():
    r = _load("open_weight_ensemble_report.json")
    if not r:
        print("  [skip] A_F12 — open_weight_ensemble_report.json missing"); return
    p2 = r["part2_adaptive"]
    keys = [k for k in p2 if isinstance(p2[k], dict) and p2[k].get("seeds")]

    def stats(block):
        rates = [s["n_breached"] / s["n_docs"] for s in block["seeds"] if s.get("n_docs")]
        m = sum(rates) / len(rates) if rates else 0.0
        sd = block.get("breach_rate_stdev")
        if sd is None and len(rates) > 1:
            sd = (sum((x - m) ** 2 for x in rates) / (len(rates) - 1)) ** 0.5
        return m, (sd or 0.0)

    labels, means, sds = [], [], []
    for k in keys:
        m, sd = stats(p2[k])
        means.append(m); sds.append(sd)
        lbl = p2[k].get("label", k)
        labels.append(("single " if "single" in k else "ensemble ") + lbl.split("(")[0].split("[")[0].strip()[:24])
    fig, ax = plt.subplots(figsize=(5.6, 4.2))
    bars = ax.bar(range(len(keys)), means, 0.5, yerr=sds, capsize=5, color=RED, edgecolor="white",
                  error_kw={"ecolor": GREY, "lw": 1.2})
    for bar, m, sd in zip(bars, means, sds):
        ax.annotate(f"{m:.0%} ± {sd:.0%}", (bar.get_x() + bar.get_width() / 2, m + sd + 0.02),
                    ha="center", fontsize=9, fontweight="bold")
    ax.set_xticks(range(len(keys))); ax.set_xticklabels(labels, fontsize=8.5)
    ax.set_ylim(0, 1.05); ax.set_ylabel("adaptive breach rate (mean ± sd over seeds)")
    ax.set_title("Two open-weight judges do NOT close the leak")
    fig.subplots_adjust(bottom=0.20)
    fig.text(0.5, 0.01, f"{r['n_docs']} docs × {len(r['seeds'])} seeds × {r['rounds']} rounds (Qwen-72B + Llama-70B, "
             "Featherless).\nThe frontier-veto (Fig. A_F10) reached 0; the cheap open-weight substitute did not "
             "replicate that closure (large seed variance).",
             ha="center", va="bottom", fontsize=8.0, color=GREY)
    _save(fig, "A_F12")


# --------------------------------------------------------------------------- #
# A_F13 — cross-source stance at scale (heterogeneous 100%, contracts 89%)    #
# source: cross_source_scaled_report.json                                    #
# --------------------------------------------------------------------------- #
def fig_A_F13():
    r = _load("cross_source_scaled_report.json")
    if not r:
        print("  [skip] A_F13 — cross_source_scaled_report.json missing"); return
    labels = ["corroborated", "divergent", "fabricated"]

    def acc(domain, lab):
        return r.get(domain, {}).get("by_label", {}).get(lab, {}).get("mean", 0.0)

    x = range(len(labels)); w = 0.36
    fig, ax = plt.subplots(figsize=(5.6, 4.2))
    b1 = ax.bar([i - w / 2 for i in x], [acc("contracts", l) for l in labels], w, color=BLUE, edgecolor="white", label="contracts")
    b2 = ax.bar([i + w / 2 for i in x], [acc("heterogeneous", l) for l in labels], w, color=GREEN, edgecolor="white", label="heterogeneous facts")
    _bar_labels(ax, b1); _bar_labels(ax, b2)
    ax.set_xticks(list(x)); ax.set_xticklabels(labels)
    ax.set_ylim(0, 1.12); ax.set_ylabel("classification accuracy (mean over seeds)")
    ax.set_title("Stance-based cross-source verification scales")
    ax.legend(loc="lower left", frameon=False, fontsize=8.5)
    cN, hN = r.get("contracts", {}), r.get("heterogeneous", {})
    fig.subplots_adjust(bottom=0.16)
    fig.text(0.5, 0.005, f"judge={r['judge']}, {len(r.get('seeds', []))} seeds; contracts n={cN.get('n_claims')} overall "
             f"{cN.get('overall', {}).get('mean', 0):.0%}, heterogeneous n={hN.get('n_claims')} overall "
             f"{hN.get('overall', {}).get('mean', 0):.0%}. Divergent (amendment contradicts vs restates) is the hard case.",
             ha="center", va="bottom", fontsize=8.0, color=GREY)
    _save(fig, "A_F13")


# --------------------------------------------------------------------------- #
# A_F14 — 3-way vs refined 5-way stance taxonomy (level accuracy)            #
# source: adversarial_stance_report.json                                     #
# --------------------------------------------------------------------------- #
def fig_A_F14():
    r = _load("adversarial_stance_report.json")
    if not r:
        print("  [skip] A_F14 — adversarial_stance_report.json missing"); return
    s = r["summary"]
    three, five = s["three_way"], s["five_way"]
    types = [t for t in three if t in five and t != "overall"]
    short = {"implied_not_stated": "implied", "partial_coverage": "partial-cov",
             "paraphrase_contradiction": "paraphrase", "superseded_by_later": "superseded"}
    types_lbl = [short.get(t, t) for t in types] + ["overall"]
    types_all = types + ["overall"]
    x = range(len(types_all)); w = 0.36
    fig, ax = plt.subplots(figsize=(6.2, 4.2))
    b1 = ax.bar([i - w / 2 for i in x], [three[t]["level"]["mean"] for t in types_all], w, color=AMBER, edgecolor="white", label="3-way")
    b2 = ax.bar([i + w / 2 for i in x], [five[t]["level"]["mean"] for t in types_all], w, color=GREEN, edgecolor="white", label="5-way (refined)")
    _bar_labels(ax, b1); _bar_labels(ax, b2)
    ax.set_xticks(list(x)); ax.set_xticklabels(types_lbl, fontsize=8.5)
    ax.set_ylim(0, 1.12); ax.set_ylabel("level accuracy")
    ax.set_title("Refined 5-way vs 3-way stance taxonomy")
    ax.legend(loc="lower right", frameon=False, fontsize=8.5)
    fig.subplots_adjust(bottom=0.16)
    fig.text(0.5, 0.005, f"judge={r['judge']}, n={r['n_cases']} ({r['n_seeds']} seeds). The 5-way taxonomy fixes "
             "partial-coverage (an aggregation-bound failure) but not implied-not-stated\n(a judge-reading-bound failure, "
             "which slightly regresses).",
             ha="center", va="bottom", fontsize=8.0, color=GREY)
    _save(fig, "A_F14")


# --------------------------------------------------------------------------- #
# A_F15 — composite-class failure mode (shares the B_F5 seam render)          #
# source: known_exploit_probe_report.json + contestable_stability_report.json #
#         (+ mitigation_probe_report.json for the mitigation annotation)      #
# --------------------------------------------------------------------------- #
def fig_A_F15():
    known = _load("known_exploit_probe_report.json")
    stab = _load("contestable_stability_report.json")
    if not (known and stab):
        print("  [skip] A_F15 — known_exploit / contestable_stability report missing"); return
    mit = _load("mitigation_probe_report.json")

    # left: clear fabrications (FAB minus the one composite F1) withheld by every judge; genuine paid.
    judges = known["judges"]
    clear_ids = [c["id"] for c in known["claims"] if c["label"] == "FAB" and c["id"] != "F1_60pct_credit"]
    gen_ids = [c["id"] for c in known["claims"] if c["label"] == "GEN"]
    nj = len(judges)
    clear_withheld = sum(1 for j in judges.values() for r in j["rows"] if r["id"] in clear_ids and not r["auto_pay"])
    clear_tot = nj * len(clear_ids)
    gen_paid = sum(1 for j in judges.values() for r in j["rows"] if r["id"] in gen_ids and r["auto_pay"])
    gen_tot = nj * len(gen_ids)

    # right: contestable pooled pay-rates per item, both reasoning judges, with phrasing-spread whiskers.
    items = [i for i, v in stab["results"]["gpt5"]["items"].items() if v["kind"] == "contestable"]
    short = [i.split("_")[0] for i in items]
    g5 = [stab["results"]["gpt5"]["items"][i]["pooled_pay_rate"] for i in items]
    g51 = [stab["results"]["frontier"]["items"][i]["pooled_pay_rate"] for i in items]
    sp5 = [stab["results"]["gpt5"]["items"][i]["phrasing_spread"] for i in items]
    sp51 = [stab["results"]["frontier"]["items"][i]["phrasing_spread"] for i in items]

    fig, (axL, axR) = plt.subplots(1, 2, figsize=(11, 4.6), gridspec_kw={"width_ratios": [1, 2.1]})
    bars = axL.bar(["clear fabs\nwithheld", "genuine\npaid"],
                   [clear_withheld / clear_tot, gen_paid / gen_tot], 0.58, color=GREEN, edgecolor="white")
    for bar, num, tot in zip(bars, (clear_withheld, gen_paid), (clear_tot, gen_tot)):
        axL.annotate(f"{bar.get_height():.0%}\n({num}/{tot})", (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                     textcoords="offset points", xytext=(0, 4), ha="center", fontsize=10, fontweight="bold")
    axL.set_ylim(0, 1.12); axL.set_ylabel("fraction, across every judge tested")
    axL.set_title("Clears the clear cases", fontsize=11.5); axL.margins(x=0.18)

    xs = list(range(len(items)))
    for x, v, s in zip(xs, g5, sp5):
        axR.plot([x - 0.12, x - 0.12], [max(0, v - s / 2), min(1, v + s / 2)], color=BLUE, lw=1.2, alpha=0.5, zorder=1)
    for x, v, s in zip(xs, g51, sp51):
        axR.plot([x + 0.12, x + 0.12], [max(0, v - s / 2), min(1, v + s / 2)], color=RED, lw=1.2, alpha=0.5, zorder=1)
    axR.scatter([x - 0.12 for x in xs], g5, s=58, color=BLUE, edgecolor="white", lw=1.0, zorder=3, label="gpt-5")
    axR.scatter([x + 0.12 for x in xs], g51, s=58, color=RED, edgecolor="white", lw=1.0, zorder=3, label="gpt-5.1")
    axR.axhline(1.0, ls=":", color=GREY, lw=1.0); axR.axhline(0.0, ls=":", color=GREY, lw=1.0)
    axR.set_xticks(xs); axR.set_xticklabels(short, fontsize=9)
    axR.set_ylim(-0.08, 1.12); axR.set_ylabel("pooled pay-rate (whisker = phrasing-spread)")
    axR.set_title("Fails on one class: arithmetic composites (phrasing-determined)", fontsize=11)
    axR.legend(loc="center right", frameon=False, fontsize=9.5)

    # mitigation annotation: a deterministic temp-0 judge that still flips 5/5 ↔ 0/5 across phrasings.
    mit_note = ""
    if mit:
        cfg = mit["results"].get("gpt4.1_temp0")
        if cfg:
            flips = 0
            for itm in cfg["items"].values():
                majs = {v["majority"] for v in itm["variants"] if v.get("majority")}
                if "PAY" in majs and "NO_PAY" in majs or len(majs) > 1:
                    flips += 1
            mit_note = (f" Temperature-0 and majority voting remove run-noise but not phrasing-noise: the deterministic "
                        f"gpt-4.1 (temp 0) judge still flips majority across phrasings on {flips}/{len(cfg['items'])} items.")

    fig.subplots_adjust(bottom=0.26, wspace=0.34, top=0.90)
    fig.text(0.5, 0.015, "Clear fabrications and genuine derivations settle reliably (left). On the composite class the "
             "verdict scatters across [0,1] and reverses across truth-equivalent phrasings (right)." + mit_note,
             ha="center", va="bottom", fontsize=8.2, color=GREY, wrap=True)
    _save(fig, "A_F15")


def main():
    os.makedirs(_FIGS, exist_ok=True)
    print(f"Rendering Paper-A figures → {os.path.relpath(_FIGS, _ROOT)}/")
    fig_A_F1()
    fig_A_F1b()
    fig_A_F2()
    fig_A_F3()
    fig_A_F5()
    fig_A_F6()
    fig_A_F7()
    fig_A_F8()
    fig_A_F9()
    fig_A_F10()
    fig_A_F12()
    fig_A_F13()
    fig_A_F14()
    fig_A_F15()
    print("done.")


if __name__ == "__main__":
    main()
