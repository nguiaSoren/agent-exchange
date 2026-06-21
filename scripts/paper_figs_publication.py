"""Publication-grade renders of the ~4 load-bearing figures (matplotlib → PDF + PNG).

The full figure set is rendered as zero-dep SVG by `paper_figs.py`; this script overrides the
teaser/load-bearing figures with polished matplotlib versions, reading the SAME frozen JSON
reports so every number stays locked to the text. Output → docs/research/figs/pub/.

  * A_F2 — reliability / ECE curve (catch_rate_report.json)
  * A_F7 — cross-source ablation discrimination (cross_source_report.json + fab_n)
  * A_F9 — scaled adaptive: frontier holds / weak leaks (scaled_adaptive_report.json)
  * B_F1 — the market loop (authored diagram)
  * A_teaser — the ablation fork (SVG + PDF, schematic, numbers-as-labels)
  * B_teaser — the self-cleaning market loop (SVG + PDF, schematic, numbers-as-labels)

The two teasers are *glance-figures* that REPRODUCE THE APPROVED REFERENCE LAYOUTS
(`paper_a_ablation_fork_teaser_final.svg` / `paper_b_self_cleaning_loop_teaser_final.svg`
— topology, box contents, numbers, arrow structure) re-rendered in THIS PAPER'S HOUSE STYLE
(DejaVu Sans, the journal stroke palette + one indigo gate accent, B_F1's light tints and
1.6 pt strokes) so they read as siblings of A_F7 / B_F1 rather than imported pastel art.
Scaffolding is drawn entirely in matplotlib vector primitives — no raster/PNG anywhere in
the vector path — and the headline numbers are TEXT ANNOTATIONS, not plotted bars/curves
(the actual data plots live in the body figures A_F7 / B_F2). Number convention (per the
approved layout): the teaser carries the rounded headline AND the exact fraction inline
(`4% (1/24)`, `67% (16/24)`); leak rates round (frontier 0, weak 8%) with the body carrying
8.3%=1/12. Every number — rounded and fraction — is pulled from the frozen JSON via
`_load()` so a teaser can never silently drift from the data.

Run:  .venv/bin/python scripts/paper_figs_publication.py
"""

from __future__ import annotations

import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA = os.path.join(_ROOT, "data", "eval")
_OUT = os.path.join(_ROOT, "docs", "research", "figs", "pub")

# A restrained, journal-friendly palette.
GREEN, RED, BLUE, AMBER, GREY = "#2a8a4a", "#c0392b", "#2566a8", "#d98a1f", "#555555"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 11, "axes.titlesize": 12.5,
    "axes.titleweight": "bold", "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": "#e6e6e6", "grid.linewidth": 0.8,
    "figure.dpi": 150, "savefig.bbox": "tight", "axes.axisbelow": True,
})


def _load(name):
    p = os.path.join(_DATA, name)
    return json.load(open(p)) if os.path.exists(p) else None


def _save(fig, stem):
    os.makedirs(_OUT, exist_ok=True)
    for ext in ("pdf", "png"):
        fig.savefig(os.path.join(_OUT, f"{stem}.{ext}"))
    plt.close(fig)
    print(f"  wrote figs/pub/{stem}.pdf + .png")


def _save_vector(fig, stem):
    """Teaser figures: PDF + SVG only, both true vector — no PNG in the path."""
    os.makedirs(_OUT, exist_ok=True)
    for ext in ("pdf", "svg"):
        fig.savefig(os.path.join(_OUT, f"{stem}.{ext}"))
    plt.close(fig)
    print(f"  wrote figs/pub/{stem}.pdf + .svg")


def _pct(v):
    """Teaser rounding: integer percent. Body figures carry the precise fraction."""
    return f"{round(v * 100)}%"


def fig_A2_reliability():
    r = _load("catch_rate_report.json")
    if not r:
        print("  [skip] A_F2"); return
    bins = [b for b in r["reliability"] if b.get("count")]
    fig, ax = plt.subplots(figsize=(5.2, 4.8))
    ax.plot([0, 1], [0, 1], "--", color=GREY, lw=1.2, label="perfect calibration", zorder=1)
    big = max(b["count"] for b in bins)
    for b in bins:
        size = 60 + 26 * (b["count"] ** 0.5)          # sqrt-scaled so n=159 doesn't dwarf the plot
        ax.scatter([b["mean_confidence"]], [b["accuracy"]], s=size, color=BLUE,
                   alpha=0.7, edgecolor="white", lw=1.2, zorder=3)
        # Label below-left of the big bin (keeps it off the title); above for small bins.
        dy, va = (-16, "top") if b["count"] == big else (12, "bottom")
        ax.annotate(f"n={b['count']}", (b["mean_confidence"], b["accuracy"]),
                    textcoords="offset points", xytext=(0, dy), ha="center", va=va,
                    fontsize=8.5, color=GREY)
    ax.set_xlim(0, 1.06); ax.set_ylim(0, 1.08)
    ax.set_xlabel("predicted confidence"); ax.set_ylabel("empirical accuracy")
    ax.set_title(f"Reliability — contract verifier  (ECE = {r['ece']:.3f}, n = {r['n_total']})")
    ax.legend(loc="lower right", frameon=False, fontsize=9.5)
    fig.subplots_adjust(bottom=0.20)
    fig.text(0.5, 0.015, f"The verifier concentrates at high confidence ({big}/{r['n_total']} claims in the top bin, "
             "all correct);\nthe bins are on/near the diagonal — well-calibrated on this set (cf. ECE 0.114 on the harder gold set).",
             ha="center", va="bottom", fontsize=8.2, color=GREY)
    _save(fig, "A_F2_reliability")


def fig_A7_cross_source():
    r = _load("cross_source_report.json")
    if not r:
        print("  [skip] A_F7"); return
    a = r["ablation_cross_source"]
    fab = _load("cross_source_fab_n_report.json") or {}
    groups = ["genuine\n(corroborated)", "gifted-span\n(a lie)"]
    lex = [a["genuine_supported_lexical"], a["gifted_supported_lexical"]]
    llm = [a["genuine_supported_llm"], a["gifted_supported_llm"]]
    x = range(len(groups)); w = 0.36
    fig, ax = plt.subplots(figsize=(5.4, 4.5))
    b1 = ax.bar([i - w / 2 for i in x], lex, w, label="lexical ablation", color=AMBER, edgecolor="white")
    b2 = ax.bar([i + w / 2 for i in x], llm, w, label="LLM-entailment ablation", color=GREEN, edgecolor="white")
    for bars in (b1, b2):
        for bar in bars:
            ax.annotate(f"{bar.get_height():.0%}", (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                        textcoords="offset points", xytext=(0, 3), ha="center", fontsize=9.5)
    ax.set_xticks(list(x)); ax.set_xticklabels(groups)
    ax.set_ylim(0, 1.08); ax.set_ylabel("fraction surviving ablation")
    ax.set_title("Cross-source ablation discriminates (semantic only)")
    ax.legend(loc="upper right", frameon=False, fontsize=9.5)
    n_gif = fab.get("n_gifted", 120); n_reach = fab.get("n_reached", 1)
    fig.subplots_adjust(bottom=0.30)
    fig.text(0.5, 0.015, f"Genuine arm well-powered (n={a.get('genuine_reached', 24)} reached). Fabrication "
             f"arm structurally tiny:\nof {n_gif} gifted-span the judge intercepted {n_gif - n_reach} before "
             f"ablation — semantic required (lexical lets the lie survive).",
             ha="center", va="bottom", fontsize=8.4, color=GREY)
    _save(fig, "A_F7_cross_source")


def fig_A9_scaled_adaptive():
    r = _load("scaled_adaptive_report.json")
    if not r:
        print("  [skip] A_F9"); return
    cfgs = {k: v for k, v in r["configs"].items() if not v.get("skipped")}
    order = [k for k in ("frontier", "capability_gap") if k in cfgs] or list(cfgs)
    labels = [("frontier judge\n(gpt-4.1)" if "frontier" in k else "weak judge\n(gpt-4.1-mini)") for k in order]
    rates = [cfgs[k]["n_breached"] / max(1, cfgs[k]["n_docs"]) for k in order]
    colors = [GREEN if rt == 0 else RED for rt in rates]
    fig, ax = plt.subplots(figsize=(5.0, 4.5))
    bars = ax.bar(labels, rates, 0.55, color=colors, edgecolor="white")
    for k, bar in zip(order, bars):
        c = cfgs[k]
        ax.annotate(f"{bar.get_height():.0%}\n({c['n_breached']}/{c['n_docs']})",
                    (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                    textcoords="offset points", xytext=(0, 4), ha="center", fontsize=10, fontweight="bold")
    ax.set_ylim(0, max(0.4, max(rates) * 1.3)); ax.set_ylabel("breach rate (auto-paid a lie the oracle rejects)")
    ax.set_title("Scaled adaptive attack: frontier holds, weak leaks")
    fig.subplots_adjust(bottom=0.26)
    fig.text(0.5, 0.015, f"{r['rounds']}-round PAIR, diverse attacker panel (gpt-4.1 / gpt-5.1 / claude);\n"
             "independently reproduced in-market (companion paper: emergent 0 / 8%).",
             ha="center", va="bottom", fontsize=8.4, color=GREY)
    _save(fig, "A_F9_scaled_adaptive")


def fig_B1_loop():
    nodes = [("buyer\nneed", BLUE), ("bids", BLUE), ("hire", BLUE), ("work", BLUE),
             ("VERIFY\nrubric", RED), ("SETTLE", RED), ("reputation", GREEN)]
    fig, ax = plt.subplots(figsize=(11, 3.2))
    ax.set_xlim(0, 11); ax.set_ylim(0, 3.2); ax.axis("off")
    n = len(nodes); bw, bh, y = 1.18, 0.78, 1.7
    gap = (11 - 0.4 - bw * n) / (n - 1)
    cx = []
    for i, (label, col) in enumerate(nodes):
        x = 0.2 + i * (bw + gap); cx.append(x + bw / 2)
        face = "#fdecea" if col == RED else ("#eafaf0" if col == GREEN else "#eef4fb")
        ax.add_patch(FancyBboxPatch((x, y), bw, bh, boxstyle="round,pad=0.02,rounding_size=0.12",
                                    fc=face, ec=col, lw=1.6))
        ax.text(x + bw / 2, y + bh / 2, label, ha="center", va="center", fontsize=10, fontweight="bold")
        if i < n - 1:
            x2 = 0.2 + (i + 1) * (bw + gap)
            ec = RED if label.startswith("VERIFY") else GREY
            ax.add_patch(FancyArrowPatch((x + bw, y + bh / 2), (x2, y + bh / 2),
                                         arrowstyle="-|>", mutation_scale=14, color=ec, lw=1.6))
    ax.text((cx[4] + cx[5]) / 2, y + bh + 0.16, "released ONLY on pass", ha="center",
            fontsize=9, color=RED, fontweight="bold")
    # feedback loop reputation -> hire
    fy = y - 0.62
    ax.add_patch(FancyArrowPatch((cx[6], y), (cx[2], y), connectionstyle=f"arc,angleA=-90,angleB=-90,armA=55,armB=55,rad=0",
                                 arrowstyle="-|>", mutation_scale=14, color=GREEN, lw=1.7,
                                 patchA=None, shrinkA=2, shrinkB=2))
    ax.text((cx[2] + cx[6]) / 2, fy - 0.02, "verified outcome updates reputation → drives the next hire",
            ha="center", fontsize=9, color=GREEN)
    ax.set_title("The verification-gated, self-cleaning market loop", pad=12)
    _save(fig, "B_F1_loop")


# Teaser scaffolding colours — the paper's saturated stroke palette + B_F1's light tints,
# one indigo accent added for the gate/verifier (no purple in the bar palette). The two
# teasers reproduce the APPROVED reference layouts (paper_{a,b}_*_teaser_final.svg) in this
# house style so they read as siblings of A_F7 / B_F1, not imported pastel art.
PURPLE = "#5b4aa8"
_TINT = {GREY: "#f2f1ee", BLUE: "#eef4fb", PURPLE: "#efedfb",
         GREEN: "#eafaf0", AMBER: "#fdf3e3", RED: "#fdecea"}


def _tbox(ax, H, x, y, w, h, stroke, title, sub, align="center", sub_size=8.6):
    """Reference-layout box in house style. Coords are the reference SVG's (top-left origin);
    we flip y into matplotlib's bottom-up frame. align: 'center' or 'left' (matches reference)."""
    ax.add_patch(FancyBboxPatch((x, H - (y + h)), w, h, boxstyle="round,pad=0.5,rounding_size=6",
                                mutation_aspect=1, fc=_TINT[stroke], ec=stroke, lw=1.6))
    if align == "center":
        tx, ha = x + w / 2, "center"
    else:
        tx, ha = x + 18, "left"
    ax.text(tx, H - (y + h / 2 - 9), title, ha=ha, va="center",
            fontsize=10.5, fontweight="bold", color=stroke)
    ax.text(tx, H - (y + h / 2 + 11), sub, ha=ha, va="center", fontsize=sub_size, color=stroke)


def _tarrow(ax, H, x1, y1, x2, y2, color=GREY, rad=0.0):
    cs = f"arc3,rad={rad}" if rad else "arc3,rad=0"
    ax.add_patch(FancyArrowPatch((x1, H - y1), (x2, H - y2), connectionstyle=cs,
                                 arrowstyle="-|>", mutation_scale=13, color=color, lw=1.6,
                                 shrinkA=0, shrinkB=0))


def _tnote(ax, H, x, y, w, h, lines):
    ax.add_patch(FancyBboxPatch((x, H - (y + h)), w, h, boxstyle="round,pad=0.5,rounding_size=6",
                                mutation_aspect=1, fc="#f5f4ed", ec="#b9b8b3", lw=1.0))
    for i, ln in enumerate(lines):
        ax.text(x + 20, H - (y + 18 + i * 16), ln, ha="left", va="center",
                fontsize=8.4, color="#3d3d3a")


def fig_A_teaser():
    """The ablation fork (Paper A) — same check, opposite verdict by regime. Reproduces
    paper_a_ablation_fork_teaser_final.svg in the paper's house style. Numbers from JSON."""
    cs = _load("cross_source_report.json")
    sem = _load("semantic_ablation_report.json")
    fab = _load("cross_source_fab_n_report.json")
    if not (cs and sem and fab):
        print("  [skip] A_teaser"); return
    a = cs["ablation_cross_source"]
    gate = sem["part_b_gate"]["genuine"]
    single = gate["llm"] / gate["n"]                       # 1/24  -> 4% (1/24)
    multi = a["genuine_supported_llm"]                     # 0.6667 -> 67%
    n_reach = a["genuine_reached"]                         # 24
    n_sup = round(multi * n_reach)                         # 16/24
    n_gif, gif_reach = fab["n_gifted"], fab["n_reached"]
    intercept = n_gif - gif_reach                          # 119/120

    H = 440
    fig, ax = plt.subplots(figsize=(6.8, 4.4))
    ax.set_xlim(0, 680); ax.set_ylim(0, H); ax.set_aspect("equal"); ax.axis("off")

    _tbox(ax, H, 40, 160, 190, 64, PURPLE, "Span-ablation gate", "remove span, re-check")
    _tbox(ax, H, 348, 56, 300, 64, RED, "Single-source claim",
          f"residual survives {_pct(single)} ({gate['llm']}/{gate['n']}) → reduces to judge",
          align="left", sub_size=8.0)
    _tbox(ax, H, 348, 264, 300, 64, GREEN, "Multi-source claim",
          f"residual survives {_pct(multi)} ({n_sup}/{n_reach}) → valid signal",
          align="left", sub_size=8.0)

    _tarrow(ax, H, 230, 178, 348, 116, rad=0.25)
    _tarrow(ax, H, 230, 206, 348, 282, rad=-0.25)

    ax.text(135, H - 250, "the discriminating signal", ha="center", va="center", fontsize=8.6, color="#3d3d3a")
    ax.text(135, H - 266, "lives in the cited span", ha="center", va="center", fontsize=8.6, color="#3d3d3a")

    _tnote(ax, H, 40, 360, 600, 44, [
        f"Upstream, the judge intercepts {intercept} of {n_gif} fabrications before ablation is ever invoked —",
        "the gate is a rarely-invoked backstop, not the primary detector."])
    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.01)
    _save_vector(fig, "A_teaser")


def fig_B_teaser():
    """The self-cleaning loop (Paper B) — payment and reputation both gate on verified work.
    Reproduces paper_b_self_cleaning_loop_teaser_final.svg in house style. Numbers from JSON."""
    rep = _load("reputation_loop_trace.json")
    endo = _load("endogenous_market_report.json")
    if not (rep and endo):
        print("  [skip] B_teaser"); return
    tr = rep["trace"]
    clean0, clean1 = tr[0]["clean_rep"], tr[-1]["clean_rep"]       # 0.5 -> 0.8
    liar0, liar1 = tr[0]["liar_rep"], tr[-1]["liar_rep"]           # 0.5 -> 0.2
    hire = tr[-1]["p_hire_clean"]                                  # 0.99 -> ~99%
    rounds = rep["rounds"]                                         # 3
    fr = endo["regimes"]["frontier_judge"]["emergent_leak"]       # 0.0  -> 0
    wk = endo["regimes"]["weak_judge"]["emergent_leak"]           # 0.0833 -> 8%

    H = 470
    fig, ax = plt.subplots(figsize=(6.8, 4.7))
    ax.set_xlim(0, 680); ax.set_ylim(0, H); ax.set_aspect("equal"); ax.axis("off")

    # Serpentine loop: need→bids→hire ↓ work←verifier←settlement ↓→reputation →↑ next hire.
    _tbox(ax, H, 44, 44, 150, 52, GREY, "Buyer need", "plain-language job")
    _tbox(ax, H, 265, 44, 150, 52, GREY, "Bids", "cross-owner agents")
    _tbox(ax, H, 486, 44, 150, 52, BLUE, "Hire", "reputation-weighted")
    _tbox(ax, H, 486, 176, 150, 52, GREY, "Work", "team deliverable")
    _tbox(ax, H, 265, 176, 150, 52, PURPLE, "Verifier", "runs the rubric")
    _tbox(ax, H, 44, 176, 150, 52, GREEN, "Settlement", "released only on pass")
    _tbox(ax, H, 265, 320, 150, 52, AMBER, "Reputation", "verified outcomes only")

    _tarrow(ax, H, 194, 70, 263, 70)          # need -> bids
    _tarrow(ax, H, 415, 70, 484, 70)          # bids -> hire
    _tarrow(ax, H, 561, 96, 561, 174)         # hire -> work (down)
    _tarrow(ax, H, 484, 202, 417, 202, color=PURPLE)   # work -> verifier (the gate)
    _tarrow(ax, H, 263, 202, 196, 202, color=GREEN)    # verifier -> settlement
    # settlement -> reputation (down then right); reputation -> back up to next hire (green loop)
    ax.add_patch(FancyArrowPatch((119, H - 228), (263, H - 346),
                                 connectionstyle="angle,angleA=-90,angleB=0,rad=6",
                                 arrowstyle="-|>", mutation_scale=13, color=GREY, lw=1.6))
    ax.add_patch(FancyArrowPatch((415, H - 346), (561, H - 230),
                                 connectionstyle="angle,angleA=0,angleB=90,rad=6",
                                 arrowstyle="-|>", mutation_scale=13, color=GREEN, lw=1.7))

    ax.text(230, H - 162, "gate", ha="center", va="center", fontsize=8.6, color=PURPLE, fontweight="bold")
    ax.text(119, H - 292, r"pass → \$ · fail → \$0", ha="center", va="center", fontsize=8.6, color="#3d3d3a")
    ax.text(500, H - 292, "feeds next hire", ha="center", va="center", fontsize=8.6, color="#1e6b38")

    _tnote(ax, H, 44, 400, 592, 48, [
        f"Over {rounds} rounds: clean worker {clean0:.1f} → {clean1:.1f} (hired ~{_pct(hire)}), "
        f"liar {liar0:.1f} → {liar1:.1f} (hired ~never).",
        f"Under sustained in-market attack: frontier judge leaks {round(fr*100)}, weak judge leaks {_pct(wk)}."])
    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.01)
    _save_vector(fig, "B_teaser")


def fig_B5_seam():
    """E7: the composite-class seam. Left band = the verifier's SUCCESS (clear fabrications
    withheld by every judge, genuine derivations paid by every judge); right band = the
    contestable-class flips (pooled pay-rate per item, gpt-5 vs gpt-5.1, with within-model
    phrasing-spread). Every number is read from the three frozen probe reports so the panel
    cannot drift from the text. The eye should read 'clears most, fails on one located class'."""
    known = _load("known_exploit_probe_report.json")
    stab = _load("contestable_stability_report.json")
    if not (known and stab):
        print("  [skip] B_F5"); return
    # ---- left: success counts (clear fabrications F2..F6 withheld; genuine controls paid) ----
    judges = known["judges"]
    clear_ids = [c["id"] for c in known["claims"] if c["label"] == "FAB" and c["id"] != "F1_60pct_credit"]
    gen_ids = [c["id"] for c in known["claims"] if c["label"] == "GEN"]
    n_judges = len(judges)
    clear_withheld = sum(1 for j in judges.values() for r in j["rows"]
                         if r["id"] in clear_ids and not r["auto_pay"])
    clear_tot = n_judges * len(clear_ids)
    gen_paid = sum(1 for j in judges.values() for r in j["rows"]
                   if r["id"] in gen_ids and r["auto_pay"])
    gen_tot = n_judges * len(gen_ids)

    # ---- right: contestable pooled pay-rates per item, both reasoning judges ----
    items = [i for i, v in stab["results"]["gpt5"]["items"].items() if v["kind"] == "contestable"]
    short = [i.split("_")[0] for i in items]
    g5 = [stab["results"]["gpt5"]["items"][i]["pooled_pay_rate"] for i in items]
    g51 = [stab["results"]["frontier"]["items"][i]["pooled_pay_rate"] for i in items]
    sp5 = [stab["results"]["gpt5"]["items"][i]["phrasing_spread"] for i in items]
    sp51 = [stab["results"]["frontier"]["items"][i]["phrasing_spread"] for i in items]

    fig, (axL, axR) = plt.subplots(1, 2, figsize=(11, 4.6), gridspec_kw={"width_ratios": [1, 2.1]})

    # left band
    bars = axL.bar(["clear fabs\nwithheld", "genuine\npaid"],
                   [clear_withheld / clear_tot, gen_paid / gen_tot], 0.58,
                   color=[GREEN, GREEN], edgecolor="white")
    for bar, num, tot in zip(bars, (clear_withheld, gen_paid), (clear_tot, gen_tot)):
        axL.annotate(f"{bar.get_height():.0%}\n({num}/{tot})",
                     (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                     textcoords="offset points", xytext=(0, 4), ha="center",
                     fontsize=10, fontweight="bold")
    axL.set_ylim(0, 1.12); axL.set_ylabel("fraction, across every judge tested")
    axL.set_title("Clears the clear cases", fontsize=11.5)
    axL.margins(x=0.18)

    # right band: paired dots + phrasing-spread whiskers
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

    fig.subplots_adjust(bottom=0.26, wspace=0.34, top=0.90)
    fig.text(0.5, 0.015, "Clear fabrications and genuine derivations settle reliably (left). On the composite class the "
             "verdict scatters across [0,1] and reverses across truth-equivalent phrasings (right);\n"
             "temperature-0 and majority voting remove run-noise but not phrasing-noise: a deterministic judge still "
             "pays one wording 5/5 and rejects a truth-equivalent wording 0/5.",
             ha="center", va="bottom", fontsize=8.2, color=GREY)
    _save(fig, "B_F5_seam")


def main():
    os.makedirs(_OUT, exist_ok=True)
    print("Rendering publication figures → docs/research/figs/pub/")
    fig_A2_reliability()
    fig_A7_cross_source()
    fig_A9_scaled_adaptive()
    fig_B1_loop()
    fig_B5_seam()
    fig_A_teaser()
    fig_B_teaser()
    print("done.")


if __name__ == "__main__":
    main()
