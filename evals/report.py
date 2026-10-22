from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from data.config import ROOT
from evals.harness import RESULTS, configs

FIG = ROOT / "docs" / "figures"
REPORT = RESULTS / "REPORT.md"
INK, MUTED, GRID, BASE = "#1b1f24", "#7a7f86", "#e3e3dc", "#c4c4ba"
COLORS = {
    "full": "#2a78d6",
    "single_agent": "#eb6834",
    "no_devils_advocate": "#1baf7a",
    "small_models": "#eda100",
    "no_sql_correction": "#6250d6",
}
LABELS = {"full": "Multi-agent (shipped)", "single_agent": "Single agent", "no_devils_advocate": "No devil's advocate",
          "small_models": "All 20B models", "no_sql_correction": "No SQL self-correction"}  # fmt: skip

plt.rcParams.update({
    "figure.dpi": 120, "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": BASE,
    "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True, "grid.color": GRID,
    "axes.axisbelow": True, "font.size": 10, "axes.titleweight": "bold", "axes.titlesize": 11,
})  # fmt: skip


def _load(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def summaries(suite: str) -> dict[str, dict]:
    out = {}
    for cfg in configs():
        s = _load(RESULTS / suite / f"{cfg}_summary.json")
        if s:
            out[cfg] = s
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
    order = [c for c in ("full", "no_devils_advocate", "small_models", "single_agent") if c in sc]
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
    ax.set(xlabel="List-price cost per request (USD, thousandths)", ylabel="Judge overall score (1-5)",
           title="Quality vs cost per trade request", ylim=(0.8, 5.2))  # fmt: skip
    ax.set_xlim(left=0)
    fig.tight_layout()
    fig.savefig(FIG / "quality_vs_cost.png", bbox_inches="tight")
    plt.close(fig)
    return ["ablation_scenarios.png", "quality_vs_cost.png"]


def fig_exact(ex: dict) -> list[str]:
    if not ex:
        return []
    order = [c for c in ("full", "no_sql_correction", "small_models", "single_agent") if c in ex]
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


def markdown(ex: dict, sc: dict, inj: dict | None, lv: dict, agree: dict | None) -> str:
    lines = ["# NBA-Bench results", ""]
    if lv:
        lines += ["## Rules engine vs LLMs (100 trades)", "", "| Judge | Exact | Verdict right | Approves illegal trades | Rejects legal trades | Seconds |", "|---|---|---|---|---|---|",
                  "| Rules engine | 100% | 100% | 0% | 0% | <0.001 |"]  # fmt: skip
        for m, s in lv.items():
            lines.append(
                f"| {m} | {s['exact_match']:.0%} | {s['verdict_accuracy']:.0%} | {s['false_valid_rate']:.1%} | {s['false_invalid_rate']:.1%} | {s['avg_seconds']} |"
            )
        lines.append("")
    if ex:
        lines += [
            "## Exact-answer layer",
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
        lines += ["## Open-ended trade scenarios", "",
                  "| Config | Judge overall | Goal fit | Realism | Grounding | Risk | Proposals legal | Pass every check | Avg seconds | Avg tokens | $ / request |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
        for c, s in sc.items():
            j = s["judge_mean"]
            lines.append(f"| {LABELS.get(c, c)} | {j['overall']:.2f} | {j['goal_fit']:.2f} | {j['realism']:.2f} | {j['grounding']:.2f} | {j['risk_awareness']:.2f} | "
                         f"{s['proposal_legal_rate']:.0%} | {s['proposal_pass_all_rate']:.0%} | {s['avg_seconds']} | {s['avg_tokens']:,} | {s['avg_usd_list_price']:.4f} |")  # fmt: skip
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


def main() -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    ex, sc = summaries("exact"), summaries("scenarios")
    inj = _load(RESULTS / "injection" / "summary.json")
    lv = llm_vs_rules()
    agree = _load(ROOT / "evals" / "human_labels" / "agreement.json")
    figs = fig_scenarios(sc) + fig_exact(ex) + fig_injection(inj) + fig_llm_vs_rules(lv)
    REPORT.write_text(markdown(ex, sc, inj, lv, agree), encoding="utf-8")
    print(f"wrote {REPORT} and {len(figs)} figures: {figs}")


if __name__ == "__main__":
    main()
