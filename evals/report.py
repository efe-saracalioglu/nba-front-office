from __future__ import annotations

import json
import random
import statistics
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import binomtest, wilcoxon

from data.config import ROOT
from evals.harness import RESULTS, configs, load_jsonl

FIG = ROOT / "docs" / "figures"
REPORT = RESULTS / "REPORT.md"
INK, MUTED, GRID, BASE = "#1b1f24", "#7a7f86", "#e3e3dc", "#c4c4ba"
COLORS = {
    "fixed": "#0b3f8a",
    "full": "#2a78d6",
    "single_agent": "#eb6834",
    "no_devils_advocate": "#1baf7a",
    "small_models": "#eda100",
    "no_sql_correction": "#6250d6",
}
LABELS = {
    "fixed": "Multi-agent v2 (after fixes)",
    "full": "Multi-agent v1",
    "single_agent": "Single agent",
    "no_devils_advocate": "No devil's advocate",
    "small_models": "All 20B models",
    "no_sql_correction": "No SQL self-correction",
}

plt.rcParams.update(
    {
        "figure.dpi": 120,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.edgecolor": BASE,
        "axes.labelcolor": INK,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "axes.grid": True,
        "grid.color": GRID,
        "axes.axisbelow": True,
        "font.size": 10,
        "axes.titleweight": "bold",
        "axes.titlesize": 11,
    }
)


def _load(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def summaries(suite: str) -> dict[str, dict]:
    out = {}
    v1 = RESULTS / "before_fixes" / suite / "full_summary.json"
    for cfg in configs():
        path = v1 if cfg == "full" and v1.exists() else RESULTS / suite / f"{cfg}_summary.json"
        s = _load(path)
        if s:
            out[cfg] = s
    fixed = _load(RESULTS / suite / "full_summary.json")
    if v1.exists() and fixed:
        out = {"fixed": fixed, **out}
    return out


def _hbar(
    ax, names: list[str], values: list[float], fmt: str, xmax: float, colors: list[str]
) -> None:
    bars = ax.barh(names, values, color=colors, height=0.55)
    ax.bar_label(bars, labels=[fmt.format(v) for v in values], padding=4, color=INK, fontsize=9)
    ax.set_xlim(0, xmax)
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)


def fig_scenarios(sc: dict) -> list[str]:
    if not sc:
        return []
    order = [
        c
        for c in ("fixed", "full", "no_devils_advocate", "small_models", "single_agent")
        if c in sc
    ]
    names = [LABELS[c] for c in order]
    colors = [COLORS[c] for c in order]
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.2))
    _hbar(axes[0], names, [sc[c]["judge_mean"]["overall"] for c in order], "{:.2f}", 5.5, colors)
    axes[0].set_title("Judge overall score (1-5)")
    _hbar(
        axes[1],
        names,
        [100 * sc[c]["proposal_pass_all_rate"] for c in order],
        "{:.0f}%",
        115,
        colors,
    )
    axes[1].set_title("Proposals passing every check")
    axes[1].set_yticklabels([])
    _hbar(axes[2], names, [sc[c]["judge_mean"]["grounding"] for c in order], "{:.2f}", 5.5, colors)
    axes[2].set_title("Judge grounding score (1-5)")
    axes[2].set_yticklabels([])
    fig.tight_layout()
    fig.savefig(FIG / "ablation_scenarios.png", bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(6.4, 4))
    for c in order:
        x, y = sc[c]["avg_usd_list_price"] * 1000, sc[c]["judge_mean"]["overall"]
        ax.scatter(x, y, s=90, color=COLORS[c], edgecolor="white", linewidth=1.5, zorder=3)
        ax.annotate(
            LABELS[c], (x, y), textcoords="offset points", xytext=(8, 4), fontsize=9, color=INK
        )
    ax.set(
        xlabel="List-price cost per request (USD, thousandths)",
        ylabel="Judge overall score (1-5)",
        title="Quality vs cost per trade request",
        ylim=(0.8, 5.2),
    )
    ax.set_xlim(left=0)
    fig.tight_layout()
    fig.savefig(FIG / "quality_vs_cost.png", bbox_inches="tight")
    plt.close(fig)
    return ["ablation_scenarios.png", "quality_vs_cost.png"]


def fig_exact(ex: dict) -> list[str]:
    if not ex:
        return []
    order = [
        c for c in ("fixed", "full", "no_sql_correction", "small_models", "single_agent") if c in ex
    ]
    fig, ax = plt.subplots(figsize=(6.4, 2.6))
    _hbar(
        ax,
        [LABELS[c] for c in order],
        [100 * ex[c]["accuracy"] for c in order],
        "{:.0f}%",
        115,
        [COLORS[c] for c in order],
    )
    ax.set_title(f"Exact-answer accuracy ({ex[order[0]]['questions']} questions)")
    fig.tight_layout()
    fig.savefig(FIG / "exact_accuracy.png", bbox_inches="tight")
    plt.close(fig)
    return ["exact_accuracy.png"]


def fig_injection(inj: dict | None) -> list[str]:
    if not inj:
        return []
    attacks = [
        a for a in ("status_flip", "authority", "trade_steer", "canary") if a in inj["defended"]
    ]
    fig, ax = plt.subplots(figsize=(6.4, 2.8))
    y = range(len(attacks))
    for k, (variant, color) in enumerate((("undefended", "#eb6834"), ("defended", "#2a78d6"))):
        vals = [100 * inj[variant][a]["attack_success_rate"] for a in attacks]
        bars = ax.barh(
            [i + (0.2 if k == 0 else -0.2) for i in y],
            vals,
            height=0.36,
            color=color,
            label=variant,
        )
        ax.bar_label(bars, labels=[f"{v:.0f}%" for v in vals], padding=4, fontsize=9, color=INK)
    ax.set_yticks(list(y), [a.replace("_", " ") for a in attacks])
    ax.set_xlim(0, 115)
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.legend(frameon=False, loc="lower right")
    ax.set_title("Prompt-injection success rate against the scout")
    fig.tight_layout()
    fig.savefig(FIG / "injection.png", bbox_inches="tight")
    plt.close(fig)
    return ["injection.png"]


def llm_vs_rules() -> dict[str, dict]:
    out = {}
    for path in sorted(RESULTS.glob("llm_vs_rules_*_summary.json")):
        s = _load(path)
        out[s["model"].removeprefix("ollama:")] = s
    return out


def fig_llm_vs_rules(lv: dict) -> list[str]:
    if not lv:
        return []
    names = ["rules engine", *lv]
    errors = [0.0, *(100 * s["error_rate"] for s in lv.values())]
    fig, ax = plt.subplots(figsize=(6.4, 2.6))
    _hbar(ax, names, errors, "{:.0f}%", 115, ["#1baf7a"] + ["#eb6834"] * len(lv))
    ax.set_title("Trades judged wrong (100 rule-labelled trades)")
    fig.tight_layout()
    fig.savefig(FIG / "llm_vs_rules.png", bbox_inches="tight")
    plt.close(fig)
    return ["llm_vs_rules.png"]


def markdown(
    ex: dict, sc: dict, inj: dict | None, lv: dict, agree: dict | None, jv: dict | None = None
) -> str:
    lines = ["# NBA-Bench results", ""]
    if lv:
        lines += [
            "## Rules engine vs LLMs (100 trades)",
            "",
            "| Judge | Exact | Verdict right | Approves illegal trades | Rejects legal trades | Seconds |",
            "|---|---|---|---|---|---|",
            "| Rules engine | 100% | 100% | 0% | 0% | <0.001 |",
        ]
        for m, s in lv.items():
            lines.append(
                f"| {m} | {s['exact_match']:.0%} | {s['verdict_accuracy']:.0%} | {s['false_valid_rate']:.1%} | {s['false_invalid_rate']:.1%} | {s['avg_seconds']} |"
            )
        lines.append("")
    if ex:
        lines += [
            "## Exact-answer layer",
            "",
            "Ablation rows (v1 and its variants) share one system version; v2 is the shipped system after the fixes below.",
            "",
            "| Config | Accuracy | Routed to stats | SQL right first try | Avg seconds | Avg tokens |",
            "|---|---|---|---|---|---|",
        ]
        for c, s in ex.items():
            lines.append(
                f"| {LABELS.get(c, c)} | {s['accuracy']:.0%} | {s['routed_to_stats']:.0%} | {s['sql_first_try_ok']:.0%} | {s['avg_seconds']} | {s['avg_tokens']:,} |"
            )
        lines.append("")
    if sc:
        lines += [
            "## Open-ended trade scenarios",
            "",
            "Ablation rows (v1 and its variants) share one system version; v2 is the shipped system after the fixes below.",
            "",
            "| Config | Judge overall | Goal fit | Realism | Grounding | Risk | Proposals legal | Pass every check | Avg seconds | Avg tokens | $ / request |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for c, s in sc.items():
            j = s["judge_mean"]
            lines.append(
                f"| {LABELS.get(c, c)} | {j['overall']:.2f} | {j['goal_fit']:.2f} | {j['realism']:.2f} | {j['grounding']:.2f} | {j['risk_awareness']:.2f} | "
                f"{s['proposal_legal_rate']:.0%} | {s['proposal_pass_all_rate']:.0%} | {s['avg_seconds']} | {s['avg_tokens']:,} | {s['avg_usd_list_price']:.4f} |"
            )
        lines.append("")
    if inj:
        lines += [
            "## Prompt injection against the scout",
            "",
            "| Attack | Undefended success | Defended success | Defended flagged |",
            "|---|---|---|---|",
        ]
        for a in ("status_flip", "authority", "trade_steer", "canary", "benign"):
            if a in inj["defended"]:
                d, u = inj["defended"][a], inj["undefended"][a]
                lines.append(
                    f"| {a.replace('_', ' ')} | {u['attack_success_rate']:.0%} | {d['attack_success_rate']:.0%} | {d['flagged_rate']:.0%} |"
                )
        lines.append("")
    if jv:
        g = jv["groups"]
        names = {
            "empty_or_error": "Empty reply or crash",
            "no_trade_reply": "No trade proposed",
            "all_pass": "Every proposal passes every check",
            "some_fail": "Some proposal fails a check",
        }
        lines += [
            "## Judge checked against deterministic checks",
            "",
            f"All {jv['replies']} scenario replies, grouped by what the rules engine and constraint checks found.",
            "",
            "| Group | n | Goal fit | Realism | Grounding | Risk | Overall |",
            "|---|---|---|---|---|---|---|",
        ]
        for k, label in names.items():
            if k in g:
                v = g[k]
                lines.append(
                    f"| {label} | {v['n']} | {v['goal_fit']:.2f} | {v['realism']:.2f} | {v['grounding']:.2f} | {v['risk_awareness']:.2f} | {v['overall']:.2f} |"
                )
        a = jv["auc_all_pass_vs_some_fail"]
        lines += [
            "",
            f"Empty replies scored 1: {jv['empty_scored_1']:.0%}. Probability the judge ranks a fully passing reply above one with a failing proposal (AUC): "
            f"overall {a['overall']}, goal fit {a['goal_fit']}, grounding {a['grounding']}.",
            "",
        ]
    if agree:
        lines += [
            "## Judge vs human labels",
            "",
            "| Dimension | n | Spearman | Weighted kappa | Within one point | Judge minus human |",
            "|---|---|---|---|---|---|",
        ]
        for d, a in agree.items():
            lines.append(
                f"| {d.replace('_', ' ')} | {a['n']} | {a['spearman']} | {a['weighted_kappa']} | {a['within_one']:.0%} | {a['judge_minus_human_mean']:+.2f} |"
            )
        lines.append("")
    return "\n".join(lines)


def _rows(path: Path) -> dict[str, dict]:
    return {r["id"]: r for r in load_jsonl(path)} if path.exists() else {}


def paired(before: list[float], after: list[float], seed: int = 0) -> dict:
    diff = [a - b for a, b in zip(after, before, strict=True)]
    rng = random.Random(seed)
    boots = sorted(statistics.mean(rng.choices(diff, k=len(diff))) for _ in range(10_000))
    nonzero = [d for d in diff if d]
    return {
        "mean_diff": round(statistics.mean(diff), 2),
        "ci95": [round(boots[249], 2), round(boots[9749], 2)],
        "p": round(float(wilcoxon(nonzero).pvalue), 3) if len(nonzero) > 1 else None,
        "up": sum(d > 0 for d in diff),
        "down": sum(d < 0 for d in diff),
    }


def before_after() -> dict | None:
    old = RESULTS / "before_fixes"
    ex_b, ex_a = _rows(old / "exact" / "full.jsonl"), _rows(RESULTS / "exact" / "full.jsonl")
    sc_b, sc_a = (
        _rows(old / "scenarios" / "full.jsonl"),
        _rows(RESULTS / "scenarios" / "full.jsonl"),
    )
    if not (ex_b and ex_a and sc_b and sc_a):
        return None
    fixed = sum(not ex_b[i]["correct"] and ex_a[i]["correct"] for i in ex_a if i in ex_b)
    broke = sum(ex_b[i]["correct"] and not ex_a[i]["correct"] for i in ex_a if i in ex_b)
    ids = sorted(set(sc_b) & set(sc_a))
    return {
        "exact": {
            "before": _load(old / "exact" / "full_summary.json")["accuracy"],
            "after": _load(RESULTS / "exact" / "full_summary.json")["accuracy"],
            "fixed": fixed,
            "broke": broke,
            "mcnemar_p": round(float(binomtest(broke, fixed + broke, 0.5).pvalue), 4)
            if fixed + broke
            else None,
        },
        "scenarios": {
            d: paired([sc_b[i]["judge"][d] for i in ids], [sc_a[i]["judge"][d] for i in ids])
            for d in ("overall", "goal_fit", "realism", "grounding", "risk_awareness")
        },
        "pass_all": [
            _load(old / "scenarios" / "full_summary.json")["proposal_pass_all_rate"],
            _load(RESULTS / "scenarios" / "full_summary.json")["proposal_pass_all_rate"],
        ],
        "n_scenarios": len(ids),
    }


def before_after_markdown(ba: dict) -> list[str]:
    e = ba["exact"]
    lines = [
        "## System fixes: before vs after",
        "",
        "Fixes: factual one-player questions routed to the SQL analyst with their own prompt, a salary ceiling for backup and cheap targets, "
        "first-round picks required for the talent a counterparty gives up, and unambiguous payroll and hard-cap lines in the memo fact sheet.",
        "",
        f"Exact answers: {e['before']:.1%} -> {e['after']:.1%} ({e['fixed']} questions fixed, {e['broke']} broken; exact McNemar p = {e['mcnemar_p']}).",
        "",
        f"Scenarios, paired over {ba['n_scenarios']} requests, one run each; proposals passing every check {ba['pass_all'][0]:.0%} -> {ba['pass_all'][1]:.0%}:",
        "",
        "| Judge dimension | Mean change | 95% bootstrap CI | Wilcoxon p | Better / worse |",
        "|---|---|---|---|---|",
    ]
    for d, s in ba["scenarios"].items():
        lines.append(
            f"| {d.replace('_', ' ')} | {s['mean_diff']:+.2f} | [{s['ci95'][0]:+.2f}, {s['ci95'][1]:+.2f}] | {s['p']} | {s['up']} / {s['down']} |"
        )
    lines += [
        "",
        "The scenario gains are not distinguishable from run-to-run noise at this sample size; the exact-answer gain is.",
        "",
    ]
    return lines


def main() -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    ex, sc = summaries("exact"), summaries("scenarios")
    inj = _load(RESULTS / "injection" / "summary.json")
    lv = llm_vs_rules()
    agree = _load(ROOT / "evals" / "human_labels" / "agreement.json")
    figs = fig_scenarios(sc) + fig_exact(ex) + fig_injection(inj) + fig_llm_vs_rules(lv)
    jv = _load(RESULTS / "judge_validation.json")
    text = markdown(ex, sc, inj, lv, agree, jv)
    ba = before_after()
    if ba:
        (RESULTS / "before_after.json").write_text(json.dumps(ba, indent=2), encoding="utf-8")
        text += "\n" + "\n".join(before_after_markdown(ba))
    REPORT.write_text(text, encoding="utf-8")
    print(f"wrote {REPORT} and {len(figs)} figures: {figs}")


if __name__ == "__main__":
    main()
