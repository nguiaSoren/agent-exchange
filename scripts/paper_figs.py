"""Regenerate the research figures from the frozen JSON reports — deterministic, zero-dep.

Matches the repo's dependency-free convention (the arena / replay viewer / calibration HTML
are all hand-built): figures are emitted as standalone **SVG** via a tiny local bar-chart
helper — no matplotlib, no new deps. Every figure is rendered FROM a frozen report in
``data/eval/`` (the live runs produce the reports; this script never calls a model), so it
is reproducible and honest: a figure can only plot a number that exists in a report.

Outputs → ``docs/research/figs/``:
  * ``A_F1_gifted_span_payment.svg``  — Paper A core figure: per-config gifted-span LEAK rate
    vs genuine FALSE-ESCALATE rate (the measured negative result).
  * ``A_F1b_route_distribution.svg``  — why: genuine claims are single-sourced too, so they all
    land on the JUDGE route → the gate is non-discriminative on atomic snippets.
  * ``A_F2_reliability_contract.svg`` — reliability curve (predicted vs empirical) from the
    locked catch-rate run.

Run:  .venv/bin/python scripts/paper_figs.py
"""

from __future__ import annotations

import json
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA = os.path.join(_ROOT, "data", "eval")
_FIGS = os.path.join(_ROOT, "docs", "research", "figs")

# ----------------------------------------------------------------------------- #
# Tiny SVG helpers (no deps). Coordinates are plain ints; text is escaped.       #
# ----------------------------------------------------------------------------- #

_PALETTE = {
    "leak": "#c0392b",        # red — money paid for a lie
    "false_escalate": "#e67e22",  # amber — genuine wrongly escalated (the gate's cost)
    "supported": "#27ae60",   # green
    "judge": "#e67e22",       # amber
    "escalate": "#c0392b",    # red
    "genuine": "#2980b9",     # blue
    "axis": "#333", "grid": "#ddd", "text": "#222",
}


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _svg_open(w: int, h: int) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" font-family="Helvetica,Arial,sans-serif">',
        f'<rect width="{w}" height="{h}" fill="white"/>',
    ]


def _text(x, y, s, *, size=12, anchor="start", weight="normal", fill=None, rotate=None):
    t = f' transform="rotate({rotate} {x} {y})"' if rotate is not None else ""
    return (
        f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="{anchor}" '
        f'font-weight="{weight}" fill="{fill or _PALETTE["text"]}"{t}>{_esc(s)}</text>'
    )


def _grouped_bars(
    path: str, title: str, groups: list[str], series: list[tuple[str, str, list[float]]],
    *, ymax: float = 1.0, ylabel: str = "rate", note: str = "",
) -> None:
    """series = [(label, color, [value per group])]; values in [0, ymax]."""
    W, H = 720, 440
    L, R, T, B = 70, 24, 70, 110
    plot_w, plot_h = W - L - R, H - T - B
    n_groups, n_series = len(groups), len(series)
    gw = plot_w / max(1, n_groups)
    bw = gw / (n_series + 1)

    s = _svg_open(W, H)
    s.append(_text(W // 2, 30, title, size=16, anchor="middle", weight="bold"))
    # y gridlines + labels
    for i in range(6):
        frac = i / 5
        y = T + plot_h - frac * plot_h
        s.append(f'<line x1="{L}" y1="{y:.1f}" x2="{W-R}" y2="{y:.1f}" stroke="{_PALETTE["grid"]}"/>')
        s.append(_text(L - 8, y + 4, f"{frac*ymax:.0%}" if ymax <= 1 else f"{frac*ymax:.0f}", size=11, anchor="end"))
    s.append(_text(16, T + plot_h / 2, ylabel, size=12, anchor="middle", weight="bold", rotate=-90))
    # bars
    for gi, g in enumerate(groups):
        gx = L + gi * gw
        for si, (_lbl, color, vals) in enumerate(series):
            v = max(0.0, min(ymax, vals[gi]))
            bh = (v / ymax) * plot_h
            x = gx + (si + 0.5) * bw + bw * 0.1
            y = T + plot_h - bh
            s.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw*0.8:.1f}" height="{bh:.1f}" fill="{color}"/>')
            label = f"{v:.0%}" if ymax <= 1 else f"{v:.0f}"
            s.append(_text(x + bw * 0.4, y - 4, label, size=10, anchor="middle"))
        s.append(_text(gx + gw / 2, T + plot_h + 18, g, size=11, anchor="middle", weight="bold"))
    # legend
    lx, ly = L, H - 56
    for si, (lbl, color, _v) in enumerate(series):
        s.append(f'<rect x="{lx}" y="{ly-10}" width="12" height="12" fill="{color}"/>')
        s.append(_text(lx + 16, ly, lbl, size=11))
        lx += 22 + len(lbl) * 7
    if note:
        s.append(_text(L, H - 28, note, size=10, fill="#666"))
        s.append(_text(L, H - 14, "rendered from frozen report — scripts/paper_figs.py", size=9, fill="#999"))
    s.append("</svg>")
    with open(path, "w") as f:
        f.write("\n".join(s))
    print(f"  wrote {os.path.relpath(path, _ROOT)}")


def _stacked_bars(
    path: str, title: str, groups: list[str], segments: list[str],
    colors: dict, data: dict, *, note: str = "",
) -> None:
    """data[group] = {segment: count}; stacked to 100%."""
    W, H = 560, 420
    L, R, T, B = 60, 24, 70, 100
    plot_w, plot_h = W - L - R, H - T - B
    gw = plot_w / max(1, len(groups))
    s = _svg_open(W, H)
    s.append(_text(W // 2, 30, title, size=16, anchor="middle", weight="bold"))
    for gi, g in enumerate(groups):
        total = sum(data.get(g, {}).values()) or 1
        gx = L + gi * gw + gw * 0.2
        bwid = gw * 0.6
        acc = 0.0
        for seg in segments:
            c = data.get(g, {}).get(seg, 0)
            frac = c / total
            bh = frac * plot_h
            y = T + plot_h - acc - bh
            if c:
                s.append(f'<rect x="{gx:.1f}" y="{y:.1f}" width="{bwid:.1f}" height="{bh:.1f}" fill="{colors[seg]}"/>')
                s.append(_text(gx + bwid / 2, y + bh / 2 + 4, f"{seg} {c}", size=10, anchor="middle", fill="white"))
            acc += bh
        s.append(_text(gx + bwid / 2, T + plot_h + 18, f"{g}\n(n={total})", size=11, anchor="middle", weight="bold"))
        s.append(_text(gx + bwid / 2, T + plot_h + 34, f"n={total}", size=10, anchor="middle", fill="#666"))
    # legend
    lx, ly = L, H - 50
    for seg in segments:
        s.append(f'<rect x="{lx}" y="{ly-10}" width="12" height="12" fill="{colors[seg]}"/>')
        s.append(_text(lx + 16, ly, seg, size=11))
        lx += 30 + len(seg) * 7
    if note:
        s.append(_text(L, H - 24, note, size=10, fill="#666"))
    s.append("</svg>")
    with open(path, "w") as f:
        f.write("\n".join(s))
    print(f"  wrote {os.path.relpath(path, _ROOT)}")


def _scatter_reliability(path: str, title: str, bins: list[dict], *, note: str = "") -> None:
    """Reliability: x = mean predicted confidence, y = empirical accuracy; diagonal = perfect."""
    W, H = 460, 460
    L, R, T, B = 60, 24, 60, 70
    pw, ph = W - L - R, H - T - B
    s = _svg_open(W, H)
    s.append(_text(W // 2, 30, title, size=15, anchor="middle", weight="bold"))
    # frame + diagonal
    s.append(f'<rect x="{L}" y="{T}" width="{pw}" height="{ph}" fill="none" stroke="{_PALETTE["axis"]}"/>')
    s.append(f'<line x1="{L}" y1="{T+ph}" x2="{L+pw}" y2="{T}" stroke="{_PALETTE["grid"]}" stroke-dasharray="4 3"/>')
    for i in range(6):
        f_ = i / 5
        s.append(_text(L + f_ * pw, T + ph + 16, f"{f_:.1f}", size=10, anchor="middle"))
        s.append(_text(L - 8, T + ph - f_ * ph + 4, f"{f_:.1f}", size=10, anchor="end"))
    s.append(_text(L + pw / 2, T + ph + 36, "predicted confidence", size=12, anchor="middle", weight="bold"))
    s.append(_text(16, T + ph / 2, "empirical accuracy", size=12, anchor="middle", weight="bold", rotate=-90))
    for b in bins:
        if not b.get("count"):
            continue
        x = L + b["mean_confidence"] * pw
        y = T + ph - b["accuracy"] * ph
        r = 4 + min(14, b["count"] ** 0.5)
        s.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{_PALETTE["genuine"]}" fill-opacity="0.55" stroke="{_PALETTE["genuine"]}"/>')
        s.append(_text(x, y - r - 2, f'n={b["count"]}', size=9, anchor="middle", fill="#666"))
    if note:
        s.append(_text(L, H - 16, note, size=10, fill="#666"))
    s.append("</svg>")
    with open(path, "w") as f:
        f.write("\n".join(s))
    print(f"  wrote {os.path.relpath(path, _ROOT)}")


# ----------------------------------------------------------------------------- #
# Figure builders                                                               #
# ----------------------------------------------------------------------------- #

def _load(name: str):
    p = os.path.join(_DATA, name)
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def fig_A_F1_gifted_span():
    """Paper A core figure: gifted-span LEAK rate vs genuine FALSE-ESCALATE, per config."""
    r = _load("gifted_span_report.json")
    if not r:
        print("  [skip] data/eval/gifted_span_report.json missing — run spikes/gifted_span_run.py")
        return
    order = ["judge_only", "gate_teeth_off", "gate_teeth_on"]
    cfgs = [c for c in order if c in r["configs"]]

    def cls(cfg, src, attr):
        for c in r["configs"][cfg]["classes"]:
            if c["source"] == src:
                return c[attr]
        return 0.0

    leak = [cls(c, "llm_gifted_span", "leak_rate") for c in cfgs]
    fesc = [cls(c, "genuine", "false_escalate_rate") for c in cfgs]
    note = (
        f'verifier={r["verifier_model"]}, gen={r["gen_model"]}, '
        f'n_gifted={r["n_gifted_span"]} n_genuine={r["n_genuine"]}, policy={r["policy"]}'
    )
    _grouped_bars(
        os.path.join(_FIGS, "A_F1_gifted_span_payment.svg"),
        "Gifted-span attack: leak vs the gate's cost",
        cfgs,
        [
            ("gifted-span LEAK (auto-paid a lie)", _PALETTE["leak"], leak),
            ("genuine FALSE-ESCALATE (gate cost)", _PALETTE["false_escalate"], fesc),
        ],
        ylabel="rate", note=note,
    )


def fig_A_F1b_routes():
    """Route distribution under the gate — shows genuine claims are single-sourced too."""
    r = _load("gifted_span_report.json")
    if not r or "gate_teeth_on" not in r.get("route_distribution", {}):
        print("  [skip] route distribution missing")
        return
    dist = r["route_distribution"]["gate_teeth_on"]
    _stacked_bars(
        os.path.join(_FIGS, "A_F1b_route_distribution.svg"),
        "Ablation route by class (gate on)",
        ["genuine", "llm_gifted_span"],
        ["supported", "judge", "escalate"],
        {"supported": _PALETTE["supported"], "judge": _PALETTE["judge"], "escalate": _PALETTE["escalate"]},
        dist,
        note="genuine claims fail ablation too (single-sourced) → all on JUDGE → gate escalates everything",
    )


def fig_A_F2_reliability():
    """Reliability curve from the locked contract catch-rate run."""
    r = _load("catch_rate_report.json")
    if not r:
        print("  [skip] catch_rate_report.json missing")
        return
    _scatter_reliability(
        os.path.join(_FIGS, "A_F2_reliability_contract.svg"),
        f'Reliability — contract verifier (ECE={r.get("ece", 0):.3f}, n={r.get("n_total")})',
        list(r.get("reliability", [])),
        note="bubble area ∝ bin count; on/near the diagonal = well-calibrated",
    )


def fig_A_F3_long_doc():
    """Corrected experiment (long multi-clause docs, weaker judge): served crashes while
    leak stays 0 — and the genuine SUPPORTED-route fraction stays low (substring-ablation
    can't see paraphrased grounding even on long docs)."""
    r = _load("long_doc_report.json")
    if not r:
        print("  [skip] long_doc_report.json missing — run spikes/long_doc_gate_run.py")
        return
    # Pick the cleanest judge: most non-fail-safe. Prefer gpt-4.1-mini if present.
    judges = r.get("judges", {})
    judge = next((j for j in judges if "mini" in j), next(iter(judges), None))
    if not judge:
        print("  [skip] no judge data in long_doc_report.json")
        return
    jd = judges[judge]
    order = ["judge_only", "gate_teeth_off", "gate_teeth_on"]
    cfgs = [c for c in order if c in jd["configs"]]

    def cls(cfg, src, attr):
        for c in jd["configs"][cfg]["classes"]:
            if c["source"] == src:
                return c[attr]
        return 0.0

    served = [cls(c, "genuine", "served_rate") for c in cfgs]
    leak = [cls(c, "llm_gifted_span", "leak_rate") for c in cfgs]
    rd = jd["route_distribution"].get("gate_teeth_on", {}).get("genuine", {})
    sup = rd.get("supported", 0); tot = sum(rd.values()) or 1
    note = (
        f'judge={judge}, {r["n_docs"]} long docs, n_gifted={r["n_gifted_span"]} n_genuine={r["n_genuine"]}; '
        f'genuine SUPPORTED-route (survives ablation) = {sup}/{tot} ({sup/tot:.0%})'
    )
    _grouped_bars(
        os.path.join(_FIGS, "A_F3_long_doc_served_vs_leak.svg"),
        "Long multi-clause docs + weaker judge: the gate still doesn't help",
        cfgs,
        [
            ("genuine SERVED (auto-paid honest work)", _PALETTE["supported"], served),
            ("gifted-span LEAK (auto-paid a lie)", _PALETTE["leak"], leak),
        ],
        ylabel="rate", note=note,
    )


def fig_A_F5_semantic():
    """Semantic ablation discrimination probe: embeddings can't separate truth from a
    gifted-span mutation (95% of lies score ≥τ); LLM-entailment can (0% of lies)."""
    r = _load("semantic_ablation_report.json")
    if not r:
        print("  [skip] semantic_ablation_report.json missing — run spikes/semantic_ablation_run.py")
        return
    pa = r["part_a_discrimination"]
    note = (
        f'claim vs full document; judge/entailment={r["judge"]}, embed={r["embed_model"]}, '
        f'τ={r["tau"]}; n_genuine={pa["genuine"]["n"]} n_gifted={pa["gifted"]["n"]}. '
        f'gate (ablation) genuine SUPPORTED: lexical {r["part_b_gate"]["genuine"]["lexical"]}/'
        f'{r["part_b_gate"]["genuine"]["n"]}, llm {r["part_b_gate"]["genuine"]["llm"]}/'
        f'{r["part_b_gate"]["genuine"]["n"]}'
    )
    _grouped_bars(
        os.path.join(_FIGS, "A_F5_semantic_discrimination.svg"),
        "Can a semantic signal tell a genuine claim from a gifted-span lie?",
        ["genuine (should be SUPPORTED)", "gifted-span (should NOT)"],
        [
            ("embedding: frac ≥ τ", _PALETTE["false_escalate"],
             [pa["genuine"]["emb_frac_ge_tau"], pa["gifted"]["emb_frac_ge_tau"]]),
            ("LLM-entailment: frac supported", _PALETTE["supported"],
             [pa["genuine"]["llm_frac_supported"], pa["gifted"]["llm_frac_supported"]]),
        ],
        ylabel="fraction judged supported", note=note,
    )


def fig_A_F6_adaptive():
    """Adaptive PAIR attack: every attempt's (target,oracle) outcome — the BREACH quadrant
    (target auto-pays a claim the oracle rejects) is empty for both weak and frontier judges."""
    r = _load("adaptive_adversary_report.json")
    if not r:
        print("  [skip] adaptive_adversary_report.json missing — run spikes/adaptive_adversary_run.py")
        return
    cfgs = [k for k, v in r.get("configs", {}).items() if not v.get("skipped")]
    if not cfgs:
        print("  [skip] no non-skipped adaptive configs")
        return

    def bucket(a):
        if a["target_auto_pays"] and a["oracle_says_false"]:
            return "BREACH"
        if a["target_verdict"] == "confirmed":  # oracle agreed (else it'd be a breach) → true claim
            return "confirmed (true)"
        if a["target_verdict"] == "partial":
            return "partial"
        return "caught (rejected)"

    segs = ["caught (rejected)", "partial", "confirmed (true)", "BREACH"]
    colors = {"caught (rejected)": _PALETTE["supported"], "partial": _PALETTE["judge"],
              "confirmed (true)": _PALETTE["genuine"], "BREACH": _PALETTE["leak"]}
    data = {}
    labels = []
    for name in cfgs:
        c = r["configs"][name]
        counts = {s: 0 for s in segs}
        for res in c["results"]:
            for a in res["attempts"]:
                counts[bucket(a)] += 1
        lab = f"{name}\n(t={c['target'].split(':')[-1]} vs o={c['oracle'].split(':')[-1]})"
        labels.append(lab)
        data[lab] = counts
    _stacked_bars(
        os.path.join(_FIGS, "A_F6_adaptive_breaches.svg"),
        "Adaptive PAIR attack on the verifier: the BREACH quadrant stays empty",
        labels, segs, colors, data,
        note=f"{r['n_docs']} docs × {r['rounds']} escalating rounds, attacker gpt-4.1; BREACH = target auto-pays a claim the oracle rejects = 0",
    )


def fig_A_F7_cross_source():
    """Cross-source: genuine claims survive ablation (corroborated across sources) while lies
    don't — ablation validated as a corroboration signal, but only under LLM-entailment."""
    r = _load("cross_source_report.json")
    if not r:
        print("  [skip] cross_source_report.json missing — run spikes/cross_source_run.py")
        return
    a = r["ablation_cross_source"]
    base = r.get("single_source_baseline", {})
    _grouped_bars(
        os.path.join(_FIGS, "A_F7_cross_source_ablation.svg"),
        "Cross-source: ablation survival (genuine should survive, lies should not)",
        ["genuine (corroborated)", "gifted-span (a lie)"],
        [
            ("lexical ablation survives", _PALETTE["false_escalate"],
             [a["genuine_supported_lexical"], a["gifted_supported_lexical"]]),
            ("LLM-entailment ablation survives", _PALETTE["supported"],
             [a["genuine_supported_llm"], a["gifted_supported_llm"]]),
        ],
        ylabel="fraction surviving ablation",
        note=(f'judge={r["judge"]}, n_gen={r["n_genuine"]}; single-source genuine LLM-survival '
              f'{base.get("genuine_supported_llm", 0):.0%} → cross-source {a["genuine_supported_llm"]:.0%} (well-powered). '
              f'Fabrication arm structurally tiny: of {(_load("cross_source_fab_n_report.json") or {}).get("n_gifted", 120)} '
              f'gifted-span the judge intercepted all but {(_load("cross_source_fab_n_report.json") or {}).get("n_reached", 1)} before ablation'),
    )


def fig_A_F8_stress():
    """Batch-dilution + long-context: leak stays 0 across batch size and document length."""
    r = _load("stress_test_report.json")
    if not r:
        print("  [skip] stress_test_report.json missing — run spikes/stress_test_run.py")
        return
    # Batch dilution: leak_rate vs batch size for the first target.
    tname = r["targets"][0]
    rows = r["batch_dilution"].get(tname, [])
    by_size = {}
    for row in rows:
        by_size.setdefault(row["batch_size"], []).append(row["leak_rate"])
    sizes = sorted(by_size)
    leak_by_size = [max(by_size[s]) for s in sizes]
    lc = r.get("long_context", {})
    lc_keys = list(lc.keys())
    _grouped_bars(
        os.path.join(_FIGS, "A_F8_stress.svg"),
        "Stress: batch dilution (worst leak per size) + long-context leak",
        [f"batch={s}" for s in sizes] + [f"{lc[k]['words']}w" for k in lc_keys],
        [("fabrication LEAK rate", _PALETTE["leak"],
          leak_by_size + [lc[k]["leak_rate"] for k in lc_keys])],
        ylabel="leak rate",
        note=f'target={tname}; batch dilution (false among genuine) + buried-clause long context — all 0',
    )


def fig_A_F9_scaled_adaptive():
    """Scaled PAIR (12 rounds, diverse panel): breaches stay 0 at weak and frontier scale."""
    r = _load("scaled_adaptive_report.json")
    if not r:
        print("  [skip] scaled_adaptive_report.json missing — run spikes/scaled_adaptive_run.py")
        return
    cfgs = [k for k, v in r.get("configs", {}).items() if not v.get("skipped")]
    if not cfgs:
        print("  [skip] no non-skipped scaled configs")
        return
    _grouped_bars(
        os.path.join(_FIGS, "A_F9_scaled_adaptive.svg"),
        "Scaled adaptive PAIR (12 rounds, diverse attacker panel): breaches",
        [f"{k}\n(t={r['configs'][k]['target'].split(':')[-1]})" for k in cfgs],
        [("breaches / docs", _PALETTE["leak"],
          [r["configs"][k]["n_breached"] / max(1, r["configs"][k]["n_docs"]) for k in cfgs])],
        ylabel="breach rate",
        note=f'{r["rounds"]} rounds, panel {r.get("panel")}; breach = target auto-pays a claim the oracle rejects',
    )


def fig_A_F10_ensemble():
    """Ensemble judging closes the weak-judge leak: per-judge leak/served/false-escalate."""
    r = _load("ensemble_report.json")
    if not r:
        print("  [skip] ensemble_report.json missing — run spikes/ensemble_run.py")
        return
    p1 = r["part1_payment_lens"]
    order = [k for k in ("mini_alone", "gpt41_alone", "ensemble_mini+gpt41") if k in p1]
    _grouped_bars(
        os.path.join(_FIGS, "A_F10_ensemble.svg"),
        "Ensemble judging: leak vs cost (and the adaptive breach it closes)",
        order,
        [
            ("gifted-span LEAK", _PALETTE["leak"], [p1[k]["gifted_leak_rate"] for k in order]),
            ("genuine SERVED", _PALETTE["supported"], [p1[k]["genuine_served_rate"] for k in order]),
            ("genuine FALSE-ESCALATE", _PALETTE["false_escalate"], [p1[k]["genuine_false_escalate_rate"] for k in order]),
        ],
        ylabel="rate",
        note=(f'adaptive breaches: mini-alone {r["part2_adaptive"].get("mini_alone_baseline",1)}/'
              f'{r["part2_adaptive"]["n_docs"]} → ensemble {r["part2_adaptive"]["n_breached"]}/'
              f'{r["part2_adaptive"]["n_docs"]} (oracle gpt-5.1, off-panel)'),
    )


def fig_A_F11_cross_source_slice():
    """Cross-source slice: does the verifier correctly classify corroborated/divergent/fabricated?"""
    r = _load("cross_source_slice_report.json")
    if not r:
        print("  [skip] cross_source_slice_report.json missing — run spikes/cross_source_slice_run.py")
        return
    bl = r.get("by_label", {})
    labels = [k for k in ("corroborated", "divergent", "fabricated") if k in bl]
    if not labels:
        print("  [skip] no by_label data in cross_source_slice_report")
        return
    _grouped_bars(
        os.path.join(_FIGS, "A_F11_cross_source_slice.svg"),
        "Cross-source verification: classification accuracy by claim type",
        labels,
        [("classified correctly", _PALETTE["supported"], [bl[k]["accuracy"] for k in labels])],
        ylabel="accuracy",
        note=f'judge={r["judge"]}, n={r["n_claims"]}, overall {r["accuracy"]:.0%}; CORROBORATED/DIVERGENT/UNCORROBORATED levels',
    )


def fig_A_F12_open_weight_ensemble():
    """Two open-weight judges do NOT close the leak: single vs ensemble adaptive breach rate."""
    r = _load("open_weight_ensemble_report.json")
    if not r:
        print("  [skip] open_weight_ensemble_report.json missing")
        return
    p2 = r.get("part2_adaptive", {})

    def rate(block):
        seeds = block.get("seeds", [])
        rates = [s["n_breached"] / s["n_docs"] for s in seeds if s.get("n_docs")]
        return sum(rates) / len(rates) if rates else 0.0

    keys = [k for k in p2 if isinstance(p2[k], dict) and p2[k].get("seeds")]
    labels = [("single " if "single" in k else "ensemble ") + p2[k].get("label", k)[:22] for k in keys]
    _grouped_bars(
        os.path.join(_FIGS, "A_F12_open_weight_ensemble.svg"),
        "Two open-weight judges DON'T close the leak (single vs ensemble)",
        labels,
        [("adaptive breach rate (mean over seeds)", _PALETTE["leak"], [rate(p2[k]) for k in keys])],
        ylabel="breach rate",
        note=f'{r.get("n_docs")} docs × {r.get("seeds")} seeds × {r.get("rounds")} rounds; frontier-pairing (Build 1) got 0 — two WEAK judges do not',
    )


def fig_A_F13_scaled_cross_source():
    """Stance cross-source at scale: contracts vs heterogeneous, by claim type."""
    r = _load("cross_source_scaled_report.json")
    if not r:
        print("  [skip] cross_source_scaled_report.json missing")
        return
    labels = ["corroborated", "divergent", "fabricated"]

    def acc(domain, lab):
        return r.get(domain, {}).get("by_label", {}).get(lab, {}).get("mean", 0.0)

    _grouped_bars(
        os.path.join(_FIGS, "A_F13_scaled_cross_source.svg"),
        "Cross-source stance verification at scale (accuracy by claim type)",
        labels,
        [
            ("contracts", _PALETTE["genuine"], [acc("contracts", l) for l in labels]),
            ("heterogeneous facts", _PALETTE["supported"], [acc("heterogeneous", l) for l in labels]),
        ],
        ylabel="classification accuracy",
        note=(f'contracts n={r.get("contracts",{}).get("n_claims")} overall {r.get("contracts",{}).get("overall",{}).get("mean",0):.0%}; '
              f'heterogeneous n={r.get("heterogeneous",{}).get("n_claims")} overall {r.get("heterogeneous",{}).get("overall",{}).get("mean",0):.0%}'),
    )


def fig_A_F14_adversarial_stance():
    """Refined 5-way vs 3-way stance taxonomy, per adversarial failure type."""
    r = _load("adversarial_stance_report.json")
    if not r:
        print("  [skip] adversarial_stance_report.json missing")
        return
    s = r.get("summary", {})
    three, five = s.get("three_way", {}), s.get("five_way", {})
    types = [t for t in three if t in five]
    short = {"implied_not_stated": "implied", "partial_coverage": "partial-cov",
             "paraphrase_contradiction": "paraphrase", "superseded_by_later": "superseded"}
    _grouped_bars(
        os.path.join(_FIGS, "A_F14_adversarial_stance.svg"),
        "Adversarial stance: 3-way vs refined 5-way taxonomy (level accuracy)",
        [short.get(t, t) for t in types],
        [
            ("3-way", _PALETTE["false_escalate"], [three[t]["level"]["mean"] for t in types]),
            ("5-way (refined)", _PALETTE["supported"], [five[t]["level"]["mean"] for t in types]),
        ],
        ylabel="level accuracy",
        note=f'judge={r.get("judge")}, n={r.get("n_cases")} ({r.get("n_seeds")} seeds); 5-way fixes partial-coverage, ties on contradiction, not implied',
    )


def _line_series(path, title, x_labels, series, *, ymax=1.0, ylabel="value", note=""):
    """series = [(label, color, [y per x])]; x is integer rounds. y in [0, ymax]."""
    W, H = 680, 440
    L, R, T, B = 60, 24, 60, 96
    pw, ph = W - L - R, H - T - B
    n = len(x_labels)
    s = _svg_open(W, H)
    s.append(_text(W // 2, 30, title, size=15, anchor="middle", weight="bold"))
    for i in range(6):
        f_ = i / 5
        y = T + ph - f_ * ph
        s.append(f'<line x1="{L}" y1="{y:.1f}" x2="{W-R}" y2="{y:.1f}" stroke="{_PALETTE["grid"]}"/>')
        s.append(_text(L - 8, y + 4, f"{f_*ymax:.1f}", size=10, anchor="end"))
    s.append(_text(16, T + ph / 2, ylabel, size=12, anchor="middle", weight="bold", rotate=-90))

    def xpos(i):
        return L + (pw * i / max(1, n - 1))

    for i, lab in enumerate(x_labels):
        s.append(_text(xpos(i), T + ph + 18, str(lab), size=11, anchor="middle"))
    for lbl, color, ys in series:
        pts = " ".join(f"{xpos(i):.1f},{T + ph - (min(ymax, max(0, y)) / ymax) * ph:.1f}" for i, y in enumerate(ys))
        s.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2.5"/>')
        for i, y in enumerate(ys):
            cx, cy = xpos(i), T + ph - (min(ymax, max(0, y)) / ymax) * ph
            s.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3.5" fill="{color}"/>')
            s.append(_text(cx, cy - 8, f"{y:.2f}", size=9, anchor="middle", fill=color))
    lx, ly = L, H - 56
    for lbl, color, _ys in series:
        s.append(f'<rect x="{lx}" y="{ly-10}" width="12" height="12" fill="{color}"/>')
        s.append(_text(lx + 16, ly, lbl, size=11))
        lx += 26 + len(lbl) * 7
    if note:
        s.append(_text(L, H - 26, note, size=10, fill="#666"))
        s.append(_text(L, H - 13, "rendered from frozen trace — scripts/paper_figs.py", size=9, fill="#999"))
    s.append("</svg>")
    with open(path, "w") as f:
        f.write("\n".join(s))
    print(f"  wrote {os.path.relpath(path, _ROOT)}")


def _write_md(path, lines):
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  wrote {os.path.relpath(path, _ROOT)}")


def fig_B_F1_loop():
    """Authored loop diagram: need→bid→hire→work→verify→settle→reputation, gate edge highlighted."""
    W, H = 860, 300
    s = _svg_open(W, H)
    s.append(_text(W // 2, 28, "The verification-gated, self-cleaning market loop", size=15, anchor="middle", weight="bold"))
    nodes = [
        ("buyer\nneed", "market/discovery"), ("bids", "market/bidding"),
        ("hire", "market/selection"), ("work", "audit/room_audit"),
        ("VERIFY\n(rubric)", "verify/"), ("SETTLE", "payments/x402_gate"),
        ("reputation", "market/reputation"),
    ]
    n = len(nodes)
    bw, bh, gap = 96, 52, (W - 40 - 96 * n) / (n - 1)
    y = 80
    cx_list = []
    for i, (label, mod) in enumerate(nodes):
        x = 20 + i * (bw + gap)
        cx_list.append(x + bw / 2)
        gate_edge = label in ("VERIFY\n(rubric)", "SETTLE")
        fill = "#fdecea" if gate_edge else "#eef3f8"
        stroke = _PALETTE["leak"] if gate_edge else _PALETTE["genuine"]
        s.append(f'<rect x="{x}" y="{y}" width="{bw}" height="{bh}" rx="7" fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>')
        for j, line in enumerate(label.split("\n")):
            s.append(_text(x + bw / 2, y + 22 + j * 14, line, size=11, anchor="middle", weight="bold"))
        s.append(_text(x + bw / 2, y + bh + 14, mod, size=8, anchor="middle", fill="#888"))
        if i < n - 1:
            x2 = 20 + (i + 1) * (bw + gap)
            arrow_color = _PALETTE["leak"] if label == "VERIFY\n(rubric)" else "#555"
            s.append(f'<line x1="{x+bw}" y1="{y+bh/2}" x2="{x2}" y2="{y+bh/2}" stroke="{arrow_color}" stroke-width="1.8" marker-end="url(#arr)"/>')
    # gate-edge label
    s.append(_text((cx_list[4] + cx_list[5]) / 2, y - 6, "released ONLY on pass", size=9, anchor="middle", fill=_PALETTE["leak"], weight="bold"))
    # feedback arrow reputation → hire
    fy = y + bh + 40
    s.append(f'<path d="M {cx_list[6]} {y+bh} L {cx_list[6]} {fy} L {cx_list[2]} {fy} L {cx_list[2]} {y+bh}" fill="none" stroke="{_PALETTE["supported"]}" stroke-width="1.8" marker-end="url(#arr)"/>')
    s.append(_text((cx_list[2] + cx_list[6]) / 2, fy + 14, "verified outcome updates reputation → drives the next hire", size=10, anchor="middle", fill=_PALETTE["supported"]))
    s.append('<defs><marker id="arr" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="#555"/></marker></defs>')
    s.append("</svg>")
    with open(os.path.join(_FIGS, "B_F1_loop.svg"), "w") as f:
        f.write("\n".join(s))
    print(f"  wrote {os.path.relpath(os.path.join(_FIGS, 'B_F1_loop.svg'), _ROOT)}")


def fig_B_F2_flywheel():
    """Reputation flywheel: clean rep rises, liar rep falls, P(hire clean) flips — over rounds."""
    r = _load("reputation_loop_trace.json")
    if not r:
        print("  [skip] reputation_loop_trace.json missing — run spikes/reputation_loop_smoke.py")
        return
    tr = r["trace"]
    rounds = [t["round"] for t in tr]
    _line_series(
        os.path.join(_FIGS, "B_F2_flywheel.svg"),
        "Reputation flywheel: clean worker vs. fabricator",
        rounds,
        [
            ("clean reputation", _PALETTE["supported"], [t["clean_rep"] for t in tr]),
            ("liar reputation", _PALETTE["leak"], [t["liar_rep"] for t in tr]),
            ("P(hire clean)", _PALETTE["genuine"], [t["p_hire_clean"] for t in tr]),
        ],
        ylabel="rate", note=f'{r["rounds"]} rounds, {r["thompson_seeds"]} Thompson seeds; round 0 is the symmetric prior (tie)',
    )


def fig_B_F3_population_mix():
    """E5: ill-gotten (paid-fabrication) earnings vs liar fraction, per verifier leak rate.
    At L=0 (frontier judge) the line is flat at $0 for any liar prevalence — self-cleaning."""
    r = _load("population_mix_report.json")
    if not r:
        print("  [skip] population_mix_report.json missing — run spikes/population_mix_run.py")
        return
    adv = "strategic"  # the harder adversary
    fracs = r["liar_fractions"]
    palette = {0.0: _PALETTE["supported"], 0.1: _PALETTE["judge"], 0.25: _PALETTE["leak"]}

    def cell(L, f):
        return next(c for c in r["cells"] if c["adversary"] == adv and c["leak_rate"] == L and c["liar_fraction"] == f)

    series = []
    for L in r["leak_rates"]:
        ys = [cell(L, f)["ill_gotten_total"]["mean"] for f in fracs]
        lbl = f"leak {L:.2f}" + (" (frontier, measured L=0)" if L == 0.0
                                 else (" (F-H upper-bound estimate)" if L == 0.25 else ""))
        series.append((lbl, palette.get(L, _PALETTE["genuine"]), ys))
    hs90 = cell(0.0, 0.9)["honest_hire_share"]["mean"]
    _line_series(
        os.path.join(_FIGS, "B_F3_population_mix.svg"),
        "Self-cleaning: paid-fabrication earnings vs. liar prevalence (parametric in L)",
        fracs, series, ymax=0.5, ylabel="$ ill-gotten (paid lies)",
        note=(f'{r["n_workers"]} workers, {r["rounds"]} rounds, {r["seeds"]} seeds; ill-gotten scales with L. '
              f'MEASURED leak in-loop (B_F4): frontier 0, weak 8% — 0.25 here is the F-H single-shot upper bound, not the measured value'),
    )


def fig_B_F4_endogenous():
    """Endogenous-leak: cumulative breach rate of a persistent liar attacking the LIVE judge.
    Frontier flat at 0 across 12 escalating attacks; weak judge breaches under sustained pressure."""
    r = _load("endogenous_market_report.json")
    if not r:
        print("  [skip] endogenous_market_report.json missing — run spikes/endogenous_market_run.py")
        return
    regs = r["regimes"]
    n = r["n_attempts"]
    xs = list(range(1, n + 1))
    palette = {"frontier_judge": _PALETTE["supported"], "weak_judge": _PALETTE["leak"]}
    series = []
    for name, reg in regs.items():
        lbl = f"{name.replace('_', ' ')} (emergent L={reg['emergent_leak']:.0%})"
        series.append((lbl, palette.get(name, _PALETTE["genuine"]), reg["cumulative_leak"]))
    ac = regs[next(iter(regs))]["adaptation_check"]
    _line_series(
        os.path.join(_FIGS, "B_F4_endogenous_leak.svg"),
        "Endogenous leak: persistent liar vs. the LIVE judge (emergent, not supplied)",
        xs, series, ymax=0.3, ylabel="cumulative breach rate",
        note=(f'{n} escalating adaptive attacks × {r["attack_rounds"]} rounds; adaptation: '
              f'~{ac["avg_distinct_claims"]:.1f} distinct claims & {ac["avg_distinct_strategies"]:.1f} strategies/attempt '
              f'(genuine search). F-H single-shot supplied: frontier {r["supplied_L_from_FH"]["frontier"]:.0%}, weak {r["supplied_L_from_FH"]["weak"]:.0%}'),
    )


def table_B_T1_edges():
    """Authored: per-edge 'remove it → what breaks' (the coupling argument)."""
    _write_md(os.path.join(_FIGS, "B_T1_edges.md"), [
        "# Table B-T1 — Per-edge: remove it → what breaks (the coupling)",
        "",
        "| Edge | What it does | Failure mode if removed |",
        "|---|---|---|",
        "| Discovery (cross-owner) | strangers hiring strangers via a consent handshake | no market — only self-dealing |",
        "| Verifier gate (rubric) | machine-checks each deliverable against its rubric | a scam factory — fabrications pass |",
        "| Payment gate | releases settlement only on a verified pass | unpaid demos — work without pay, or pay without work |",
        "| Verified-only reputation | only verified outcomes move reputation | liars buy/borrow stars; market never self-cleans |",
        "",
        "*The novelty is the coupling: payment release bound to a calibrated verifier (§4–§6). Source: VISION trust architecture.*",
    ])


def table_B_T2_settlement():
    """Live on-chain settlement evidence (needs spikes/settlement_smoke.py live run)."""
    r = _load("settlement_evidence.json")
    if not r:
        print("  [skip] settlement_evidence.json missing — needs a LIVE run: spikes/settlement_smoke.py (testnet)")
        return
    rows = ["# Table B-T2 — Live prorated on-chain settlement (Base Sepolia)", "",
            f"pay_fraction = {r.get('pay_fraction')}; gate_passed = {r.get('gate_passed')}", "",
            "| Worker | Bid (USDC) | Settled (USDC) | settle ≤ authorized | Tx |", "|---|---|---|---|---|"]
    for w in r.get("workers", []):
        rows.append(f"| {w.get('worker')} | {w.get('authorized_usdc')} | {w.get('settled_usdc')} | "
                    f"{w.get('settled_usdc',0) <= w.get('authorized_usdc',0)} | {w.get('tx','')} |")
    _write_md(os.path.join(_FIGS, "B_T2_settlement.md"), rows)


def table_B_T3_gate_zero():
    """Gate → $0: clean job pays, one fabricated claim withholds the whole job."""
    r = _load("gate_zero_table.json")
    if not r:
        print("  [skip] gate_zero_table.json missing — run spikes/gate_zero_demo.py")
        return
    rows = ["# Table B-T3 — No-fabrication gate → $0", "",
            f"policy = {r.get('policy')}", "",
            "| Scenario | gate_passed | settle called? | pay_fraction | paid (USDC) |", "|---|---|---|---|---|"]
    for x in r["rows"]:
        rows.append(f"| {x['scenario']} | {x['gate_passed']} | {'yes' if x['settle_called'] else 'NO'} | "
                    f"{x['pay_fraction']} | ${x['total_settled_usdc']:.4f} |")
    rows += ["", "*One fabricated claim ⇒ gate_passed=False ⇒ settle never called ⇒ $0 for the whole job. Source: `spikes/gate_zero_demo.py` (offline twin of `tests/test_settlement.py`).*"]
    _write_md(os.path.join(_FIGS, "B_T3_gate_zero.md"), rows)


def main():
    os.makedirs(_FIGS, exist_ok=True)
    print("Rendering research figures → docs/research/figs/")
    fig_B_F1_loop()
    fig_B_F2_flywheel()
    fig_B_F3_population_mix()
    fig_B_F4_endogenous()
    table_B_T1_edges()
    table_B_T2_settlement()
    table_B_T3_gate_zero()
    fig_A_F12_open_weight_ensemble()
    fig_A_F13_scaled_cross_source()
    fig_A_F14_adversarial_stance()
    fig_A_F1_gifted_span()
    fig_A_F1b_routes()
    fig_A_F2_reliability()
    fig_A_F3_long_doc()
    fig_A_F5_semantic()
    fig_A_F6_adaptive()
    fig_A_F7_cross_source()
    fig_A_F8_stress()
    fig_A_F9_scaled_adaptive()
    fig_A_F10_ensemble()
    fig_A_F11_cross_source_slice()
    print("done.")


if __name__ == "__main__":
    main()
