#!/usr/bin/env python3
"""Cold-run reproduction harness for Paper A.

Recomputes EVERY headline number in the Paper A draft directly from the frozen result files in
`data/eval/` and `data/calibration/` and checks each against the value printed in the paper. No
API calls, no model, no network; stdlib only (Wilson interval, two-sided Fisher exact, Cohen's /
Fleiss' kappa are implemented inline so no scipy/numpy is needed). A reviewer who pulls the
supplement and runs

    python scripts/repro_paper_A.py

should see every line PASS. Exit code is 0 iff all checks pass, non-zero otherwise (so this can
gate CI). Each line prints: the claim, the paper's value, the value recomputed from the frozen
data, and PASS/FAIL.

Source of truth for the numbers: `docs/research/paper-A-ablation-grounding/DRAFT.md` (== paperA.tex).
"""

from __future__ import annotations

import json
import math
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EVAL = os.path.join(_ROOT, "data", "eval")
_CAL = os.path.join(_ROOT, "data", "calibration")


def _load(path):
    return json.load(open(path))


# config name -> judge label (the five-judge gradient)
JUDGE = {
    "xcheck_openweight": "qwen-2.5-72b",
    "weak": "gpt-5.4-nano",
    "mid": "gpt-5.4",
    "xcheck_anthropic": "claude-sonnet-4.6",
    "frontier": "gpt-5.5",
}

# ----------------------------------------------------------------------------- stats (stdlib only)

def wilson(k, n, z=1.959963984540054):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    centre = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (100 * (centre - half) / d, 100 * (centre + half) / d)


def _hyper(a, r1, r2, c1):
    # P(cell=a) for 2x2 with row totals r1,r2 and first-col total c1 (Fisher null)
    n = r1 + r2
    return math.comb(r1, a) * math.comb(r2, c1 - a) / math.comb(n, c1)


def fisher_two_sided(a, b, c, d):
    # table [[a,b],[c,d]]; two-sided p = sum of all tables (same margins) with prob <= prob(obs)
    r1, r2, c1 = a + b, c + d, a + c
    p_obs = _hyper(a, r1, r2, c1)
    lo, hi = max(0, c1 - r2), min(r1, c1)
    return sum(_hyper(x, r1, r2, c1) for x in range(lo, hi + 1)
               if _hyper(x, r1, r2, c1) <= p_obs * (1 + 1e-7))


def cohen_kappa(pairs):
    n = len(pairs)
    po = sum(1 for a, b in pairs if a == b) / n
    cats = set(x for p in pairs for x in p)
    pe = sum((sum(1 for a, _ in pairs if a == c) / n) * (sum(1 for _, b in pairs if b == c) / n)
             for c in cats)
    return (po - pe) / (1 - pe) if (1 - pe) else 1.0


def fleiss_kappa(rows):
    # rows: list of (count_cat0, count_cat1) summing to N raters each
    N = rows[0][0] + rows[0][1]
    n = len(rows)
    P_bar = sum((s * s + u * u - N) / (N * (N - 1)) for s, u in rows) / n
    tot = N * n
    p0 = sum(s for s, _ in rows) / tot
    p1 = sum(u for _, u in rows) / tot
    P_e = p0 * p0 + p1 * p1
    return (P_bar - P_e) / (1 - P_e) if (1 - P_e) else 1.0


# ----------------------------------------------------------------------------- check harness

_RESULTS = []

def check(label, claimed, got, tol=0.0, fmt=str):
    if isinstance(claimed, (int, float)) and isinstance(got, (int, float)):
        ok = abs(claimed - got) <= tol
    else:
        ok = claimed == got
    _RESULTS.append(ok)
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label:54} paper={fmt(claimed):>14}  recomputed={fmt(got):>14}")


def section(title):
    print(f"\n=== {title} ===")


# ----------------------------------------------------------------------------- the checks

def main():
    print("Cold-run reproduction of Paper A headline numbers (frozen data, no API).")

    # --- C1: calibrated catch-rate / false-withhold / ECE (catch_rate_report.json) ---
    section("Contribution 1: seeded-liar catch-rate + calibration")
    cr = _load(os.path.join(_EVAL, "catch_rate_report.json"))
    tp, fp, tn, fn = cr["tp"], cr["fp"], cr["tn"], cr["fn"]
    check("catch-rate (tp/(tp+fn)) = 81/81", 1.0, tp / (tp + fn), 1e-9, lambda x: f"{x:.3f}")
    check("fabrications caught (tp, fn)", "81,0", f"{tp},{fn}")
    check("false-withhold (fp/(fp+tn)) = 2.5%", 2.469, 100 * fp / (fp + tn), 0.01, lambda x: f"{x:.3f}%")
    check("precision tp/(tp+fp)", 0.9759, tp / (tp + fp), 1e-3, lambda x: f"{x:.4f}")
    # recompute ECE from the reliability bins (not just read the stored scalar)
    bins = cr["reliability"]
    N = sum(b["count"] for b in bins)
    ece = sum(b["count"] / N * abs(b["accuracy"] - b["mean_confidence"]) for b in bins if b["count"])
    check("ECE recomputed from reliability bins = 0.015", 0.0148, ece, 5e-4, lambda x: f"{x:.4f}")
    check("ECE matches stored scalar", cr["ece"], ece, 1e-6, lambda x: f"{x:.4f}")
    cal = _load(os.path.join(_CAL, "calibration_result.json"))
    check("gold-set ECE 0.114 (set-dependence)", 0.1138, cal["ece"], 1e-3, lambda x: f"{x:.4f}")

    # --- C3: five-judge strict gradient (scaled_adaptive_report.json) ---
    section("Contribution 3: five-judge cross-vendor strict gradient (n=40)")
    rep = _load(os.path.join(_EVAL, "scaled_adaptive_report.json"))
    check("n_docs", 40, rep["n_docs"])
    check("rounds", 12, rep["rounds"])
    strict = {name: sum(1 for r in cfg["results"] if r.get("breached"))
              for name, cfg in rep["configs"].items() if not cfg.get("skipped")}
    expect = {"xcheck_openweight": 14, "weak": 6, "mid": 2, "xcheck_anthropic": 1, "frontier": 0}
    for name, e in expect.items():
        check(f"strict breaches {JUDGE[name]} ({name})", f"{e}/40", f"{strict[name]}/40")

    # Wilson 95% intervals (qwen, nano, gpt-5.4, sonnet, frontier)
    section("Contribution 3: Wilson 95% intervals + Fisher exact")
    for name, (clo, chi) in {"xcheck_openweight": (22.1, 50.5), "weak": (7.1, 29.1),
                             "mid": (1.4, 16.5), "xcheck_anthropic": (0.4, 12.9),
                             "frontier": (0.0, 8.8)}.items():
        lo, hi = wilson(strict[name], 40)
        check(f"Wilson lo {JUDGE[name]}", clo, lo, 0.15, lambda x: f"{x:.1f}")
        check(f"Wilson hi {JUDGE[name]}", chi, hi, 0.15, lambda x: f"{x:.1f}")
    # Fisher: qwen(14/40) vs frontier(0/40); weak nano(6/40) vs frontier(0/40)
    p_qf = fisher_two_sided(strict["xcheck_openweight"], 40 - strict["xcheck_openweight"], 0, 40)
    p_wf = fisher_two_sided(strict["weak"], 40 - strict["weak"], 0, 40)
    check("Fisher qwen vs frontier p=3.1e-5", 3.1e-5, p_qf, 2e-6, lambda x: f"{x:.2e}")
    check("Fisher weak vs frontier p=0.026", 0.026, p_wf, 1e-3, lambda x: f"{x:.3f}")

    # --- F-M: numeric_aggregation share (16% of attempts, 21% of contested) ---
    section("F-M: phrasing-determined composite class size")
    attempts = [a for cfg in rep["configs"].values() if not cfg.get("skipped")
                for r in cfg["results"] for a in r["attempts"]]
    tot_att = len(attempts)
    numagg = sum(1 for a in attempts if a.get("strategy") == "numeric_aggregation")
    check("total adversarial attempts = 2125", 2125, tot_att)
    check("numeric_aggregation attempts = 338", 338, numagg)
    check("numeric_aggregation share ~16%", 15.9, 100 * numagg / tot_att, 0.1, lambda x: f"{x:.1f}%")

    # --- contested zone = soft_leak OR double_confirm (the audit_contested.py rule) ---
    section("F-N: contested-zone selection + two-vendor audit")
    contested = [(name, a) for name, cfg in rep["configs"].items() if not cfg.get("skipped")
                 for r in cfg["results"] for a in r["attempts"]
                 if a.get("soft_leak") or a.get("double_confirm")]
    check("contested zone (soft_leak|double_confirm) = 110", 110, len(contested))
    na_c = sum(1 for _, a in contested if a.get("strategy") == "numeric_aggregation")
    check("numeric_aggregation in contested = 23 (21%)", 23, na_c)

    # F-N two-vendor audit (contested_audit.json)
    ca = _load(os.path.join(_EVAL, "contested_audit.json"))
    claims = ca["claims"]
    check("audit total contested = 110", 110, len(claims))

    def norm(v):
        if not v:
            return None
        u = str(v).upper()
        return "UNSUPPORTED" if "UNSUPPORTED" in u else ("SUPPORTED" if "SUPPORTED" in u else None)

    both = [(norm(c["opus_verdict"]), norm(c["gpt_verdict"])) for c in claims
            if norm(c["opus_verdict"]) and norm(c["gpt_verdict"])]
    confirmed = sum(1 for o, g in both if o == g == "UNSUPPORTED")
    agree = sum(1 for o, g in both if o == g) / len(both)
    check("confirmed real leaks (both UNSUPPORTED) = 104", 104, confirmed)
    check("raw two-vendor agreement = 95.5%", 95.5, 100 * agree, 0.1, lambda x: f"{x:.1f}%")
    check("Cohen's kappa opus-gpt = 0.263", 0.263, cohen_kappa(both), 5e-3, lambda x: f"{x:.3f}")
    # strict leaks counted in the gradient (sum of breached across judges) = 23
    check("strict-counted leaks across 5 judges = 23", 23, sum(strict.values()))
    check("undercount factor ~4.5x", 4.5, confirmed / sum(strict.values()), 0.1, lambda x: f"{x:.1f}")

    # per-judge confirmed leaks (qwen 64, nano 27, gpt-5.4 7, gpt-5.5 4, sonnet 2)
    section("F-N: per-judge confirmed leaks")
    perjudge = {}
    for c in claims:
        if norm(c["opus_verdict"]) == "UNSUPPORTED" and norm(c["gpt_verdict"]) == "UNSUPPORTED":
            perjudge[c["config"]] = perjudge.get(c["config"], 0) + 1
    for name, e in {"xcheck_openweight": 64, "weak": 27, "mid": 7, "frontier": 4,
                    "xcheck_anthropic": 2}.items():
        check(f"confirmed leaks {JUDGE[name]}", e, perjudge.get(name, 0))
    check("per-judge confirmed sum = 104", 104, sum(perjudge.values()))

    # --- three-vendor robustness (contested_audit_3vendor.json) ---
    section("F-N three-vendor robustness (offline from frozen gemini verdicts)")
    cv = _load(os.path.join(_EVAL, "contested_audit_3vendor.json"))
    three = [(norm(c["opus_verdict"]), norm(c["gpt_verdict"]), norm(c.get("gemini_verdict")))
             for c in cv["claims"]
             if norm(c["opus_verdict"]) and norm(c["gpt_verdict"]) and norm(c.get("gemini_verdict"))]
    check("gemini answered all 110", 110, sum(1 for c in cv["claims"] if norm(c.get("gemini_verdict"))))
    raw3 = sum(1 for t in three if t[0] == t[1] == t[2]) / len(three)
    rows = [(sum(x == "SUPPORTED" for x in t), sum(x == "UNSUPPORTED" for x in t)) for t in three]
    majority = sum(1 for t in three if sum(x == "UNSUPPORTED" for x in t) >= 2)
    unanimous = sum(1 for t in three if all(x == "UNSUPPORTED" for x in t))
    check("3-vendor majority UNSUPPORTED = 105", 105, majority)
    check("3-vendor unanimous UNSUPPORTED = 94", 94, unanimous)
    identical = sum(1 for t in three if t[0] == t[1] == t[2])
    check("3 vendors give identical verdict on 95/110", 95, identical)
    check("3 vendors differ on only 15/110", 15, len(three) - identical)
    check("3-way raw agreement = 86.4%", 86.4, 100 * raw3, 0.2, lambda x: f"{x:.1f}%")
    check("Fleiss' kappa (3 raters) = 0.269", 0.269, fleiss_kappa(rows), 5e-3, lambda x: f"{x:.3f}")

    # --- second domain: scientific-abstract replication of the undercount ---
    section("F-N second-domain replication (arXiv abstracts)")
    srep = _load(os.path.join(_EVAL, "sci_adaptive_report.json"))
    scfg = {n: c for n, c in srep["configs"].items() if not c.get("skipped")}
    s_strict = sum(sum(1 for r in c["results"] if r.get("breached")) for c in scfg.values())
    s_att = [a for c in scfg.values() for r in c["results"] for a in r["attempts"]]
    s_contested_sel = sum(1 for a in s_att if a.get("soft_leak") or a.get("double_confirm"))
    sca = _load(os.path.join(_EVAL, "sci_contested_audit.json"))
    s_both = [(norm(c["opus_verdict"]), norm(c["gpt_verdict"])) for c in sca["claims"]
              if norm(c["opus_verdict"]) and norm(c["gpt_verdict"])]
    s_conf = sum(1 for o, g in s_both if o == g == "UNSUPPORTED")
    s_agree = sum(1 for o, g in s_both if o == g) / len(s_both)
    s_perj = {}
    for c in sca["claims"]:
        if norm(c["opus_verdict"]) == "UNSUPPORTED" and norm(c["gpt_verdict"]) == "UNSUPPORTED":
            s_perj[c["config"]] = s_perj.get(c["config"], 0) + 1
    check("sci strict breaches across 3 judges = 3", 3, s_strict)
    check("sci contested-zone selection = 18", 18, s_contested_sel)
    check("sci audit contested = 18", 18, len(sca["claims"]))
    check("sci confirmed real leaks = 17", 17, s_conf)
    check("sci undercount ~5.7x", 5.67, s_conf / s_strict, 0.05, lambda x: f"{x:.1f}")
    check("sci two-vendor agreement = 100%", 100.0, 100 * s_agree, 0.1, lambda x: f"{x:.1f}%")
    check("sci weak judge confirmed leaks = 16", 16, s_perj.get("weak", 0))
    check("sci frontier '0 strict' hid 1 leak", 1, s_perj.get("frontier", 0))
    s_wk = sum(1 for r in scfg["weak"]["results"] if r.get("breached"))
    s_fr = sum(1 for r in scfg["frontier"]["results"] if r.get("breached"))
    nfr = len(scfg["frontier"]["results"])
    check("sci weak-vs-frontier Fisher p=0.23 (underpowered)", 0.233,
          fisher_two_sided(s_wk, len(scfg["weak"]["results"]) - s_wk, s_fr, nfr - s_fr), 5e-3, lambda x: f"{x:.3f}")

    # --- cross-source (119/120 upstream intercept; genuine survives 67% vs 4%) ---
    section("F-I cross-source: upstream intercept + ablation survival")
    fab = _load(os.path.join(_EVAL, "cross_source_fab_n_report.json"))
    check("gifted-span fabrications generated = 120", 120, fab["n_gifted"])
    check("intercepted upstream (120 - reached) = 119", 119, fab["n_gifted"] - fab["n_reached"])
    cs = _load(os.path.join(_EVAL, "cross_source_report.json"))
    abl = cs["ablation_cross_source"]
    base = cs["single_source_baseline"]
    check("genuine survive ablation ~67% (multi-source)", 0.67,
          abl.get("genuine_supported_llm", -1), 0.02, lambda x: f"{x:.2f}")
    check("genuine survive ~4% (single-source)", 0.04,
          base.get("genuine_supported_llm", -1), 0.01, lambda x: f"{x:.2f}")

    # ----------------------------------------------------------------------- summary
    npass = sum(_RESULTS)
    ntot = len(_RESULTS)
    print(f"\n{'='*72}\n  {npass}/{ntot} checks PASS")
    if npass == ntot:
        print("  ALL HEADLINE NUMBERS RECOMPUTE FROM THE FROZEN DATA.\n")
        return 0
    print("  MISMATCH — a printed statistic does not match the released data above.\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
