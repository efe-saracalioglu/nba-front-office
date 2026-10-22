from __future__ import annotations

import argparse
import html
import json
import random
from pathlib import Path

from data.config import ROOT
from evals.harness import RESULTS, load_jsonl
from evals.judge import DIMENSIONS

HERE = Path(__file__).resolve().parent
SCENARIOS = ROOT / "evals" / "nba_bench" / "scenarios.jsonl"
CONFIGS = ["full", "single_agent", "no_devils_advocate", "small_models"]
HELP = {
    "goal_fit": "Addresses the need and respects every constraint (positions, payroll line, protected picks, untouchables). No trade is fine if the constraints make one impossible.",
    "realism": "Would the other team plausibly accept? A star for role players is a 1-2.",
    "grounding": "Names, salaries, projections and payrolls match the verified facts; nothing invented.",
    "risk_awareness": "Names the real risks: age, injury, value lost, hard caps, roster spots, uncertainty.",
    "overall": "How useful this reply is to a real general manager.",
}


def pick_items(per_config: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    scenarios = {s["id"]: s for s in load_jsonl(SCENARIOS)}
    items = []
    for cfg in CONFIGS:
        path = RESULTS / "scenarios" / f"{cfg}.jsonl"
        if not path.exists():
            continue
        rows = [r for r in load_jsonl(path) if r["id"] in scenarios]
        for r in rng.sample(rows, min(per_config, len(rows))):
            items.append({"scenario": scenarios[r["id"]], "row": r, "config": cfg})
    rng.shuffle(items)
    for i, it in enumerate(items, 1):
        it["item_id"] = f"H{i:02d}"
    return items


def facts_table(checked: list[dict]) -> str:
    if not checked:
        return "<p class='muted'>No trade proposed.</p>"
    rows = []
    for i, c in enumerate(checked, 1):
        incoming = ", ".join(
            f"{f['name']} ({f.get('position') or '?'}, age {f.get('age') or '?'}, proj {f.get('projected_ws') if f.get('projected_ws') is not None else '?'} WS)"
            for f in c.get("incoming", [])
        )
        value = c.get("value") or {}
        pay = c.get("payroll_before_after")
        engine = "legal" if c["legal"] else "ILLEGAL " + html.escape(", ".join(c["violations"]))
        sent = (
            html.escape(", ".join(c.get("outgoing", [])))
            + "<br>"
            + html.escape(", ".join(c.get("picks_out", [])))
        )
        their = (
            "" if not value else "${:.1f}M".format(value.get("counterparty_value_change", 0) / 1e6)
        )
        payroll = "" if not pay else f"${pay[0] / 1e6:.1f}M → ${pay[1] / 1e6:.1f}M"
        failed = html.escape(", ".join(c["failed_checks"]) or "none")
        rows.append(
            f"<tr><td>{i}</td><td>{engine}</td><td>{html.escape(incoming)}</td><td>{sent}</td>"
            f"<td>{value.get('ws_change_for_us', '?')}</td><td>{their}</td><td>{payroll}</td><td>{failed}</td></tr>"
        )
    head = "<tr><th>#</th><th>Rules engine</th><th>We receive</th><th>We send</th><th>WS change</th><th>Their value change</th><th>Our payroll</th><th>Failed checks</th></tr>"
    return f"<div class='scroll'><table>{head}{''.join(rows)}</table></div>"


def render(items: list[dict]) -> str:
    cards = []
    for it in items:
        s, r = it["scenario"], it["row"]
        radios = "".join(
            f"<fieldset><legend>{d.replace('_', ' ')} <span class='muted' title='{html.escape(HELP[d])}'>ⓘ</span></legend>"
            + "".join(
                f"<label><input type='radio' name='{it['item_id']}.{d}' value='{v}'>{v}</label>"
                for v in range(1, 6)
            )
            + "</fieldset>"
            for d in DIMENSIONS
        )
        cards.append(
            f"<section id='{it['item_id']}'><h2>{it['item_id']} · {s['team']}</h2>"
            f"<p class='req'>{html.escape(s['request'])}</p>"
            f"<p class='muted'>Constraints: {html.escape(json.dumps(s['checks']))}</p>"
            f"<h3>Verified facts</h3>{facts_table(r['checked'])}"
            f"<h3>Reply</h3><pre>{html.escape(r.get('reply') or '(empty reply)')}</pre>"
            f"<div class='scores'>{radios}</div>"
            f"<textarea name='{it['item_id']}.note' placeholder='Optional note'></textarea></section>"
        )
    return TEMPLATE.replace("__CARDS__", "".join(cards)).replace(
        "__HELP__",
        "".join(
            f"<li><b>{d.replace('_', ' ')}</b>: {html.escape(h)}</li>" for d, h in HELP.items()
        ),
    )


TEMPLATE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>NBA-Bench Human Labels</title>
<style>
:root { --bg:#f6f6f3; --panel:#fff; --ink:#16191d; --muted:#6b7077; --line:#e2e2dc; --accent:#2a78d6; }
@media (prefers-color-scheme: dark) { :root { --bg:#111211; --panel:#1a1a19; --ink:#f0efec; --muted:#9a9a94; --line:#2c2c2a; --accent:#3987e5; } }
body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width:980px; margin:0 auto; padding:24px 16px 80px; }
section { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:16px 20px; margin:18px 0; }
h1 { margin:0 0 6px; } h2 { margin:0 0 6px; font-size:18px; } h3 { margin:14px 0 6px; font-size:14px; color:var(--muted); text-transform:uppercase; letter-spacing:.04em; }
.req { font-size:16px; font-weight:600; margin:4px 0; } .muted { color:var(--muted); font-size:13px; }
pre { white-space:pre-wrap; background:var(--bg); border:1px solid var(--line); border-radius:8px; padding:12px; max-height:420px; overflow:auto; font-size:13px; }
table { border-collapse:collapse; font-size:12.5px; width:100%; } th, td { border-bottom:1px solid var(--line); padding:5px 8px; text-align:left; vertical-align:top; }
.scroll { overflow-x:auto; }
.scores { display:flex; flex-wrap:wrap; gap:10px; margin-top:12px; }
fieldset { border:1px solid var(--line); border-radius:8px; padding:6px 10px; } legend { font-size:13px; font-weight:600; text-transform:capitalize; }
fieldset label { margin-right:8px; font-variant-numeric:tabular-nums; cursor:pointer; }
textarea { width:100%; box-sizing:border-box; margin-top:10px; min-height:44px; background:var(--bg); color:var(--ink); border:1px solid var(--line); border-radius:8px; padding:8px; font:inherit; }
.bar { position:sticky; top:0; background:var(--bg); padding:10px 0; display:flex; gap:12px; align-items:center; border-bottom:1px solid var(--line); z-index:2; }
button { font:inherit; background:var(--accent); color:#fff; border:0; border-radius:8px; padding:8px 14px; cursor:pointer; }
#out { width:100%; min-height:120px; font-family:ui-monospace, Consolas, monospace; font-size:12px; }
</style></head><body><main>
<h1>NBA-Bench human labels</h1>
<p class="muted">Score each reply 1-5 on every dimension. The system that produced it is hidden. Your answers are saved in this browser as you go.</p>
<ul class="muted">__HELP__</ul>
<div class="bar"><button id="export" type="button">Copy my labels as JSON</button><span id="progress" class="muted"></span></div>
__CARDS__
<h2>Export</h2><textarea id="out" readonly placeholder="Click the button above; paste the JSON into evals/human_labels/labels.json"></textarea>
</main>
<script>
const KEY = "nba-bench-labels";
const load = () => { try { return JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) { return {}; } };
const save = (s) => { try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) {} };
let state = load();
document.querySelectorAll("input[type=radio], textarea[name]").forEach(el => {
  if (el.type === "radio" && state[el.name] === el.value) el.checked = true;
  if (el.tagName === "TEXTAREA" && state[el.name]) el.value = state[el.name];
  el.addEventListener("change", () => { state[el.name] = el.value; save(state); progress(); });
});
function progress() {
  const sections = document.querySelectorAll("section");
  const done = [...sections].filter(s => [...s.querySelectorAll("fieldset")].every(f => f.querySelector("input:checked"))).length;
  document.getElementById("progress").textContent = `${done} / ${sections.length} replies fully scored`;
}
progress();
document.getElementById("export").addEventListener("click", async () => {
  const labels = {};
  for (const [k, v] of Object.entries(state)) { const [id, field] = k.split("."); (labels[id] ||= {})[field] = field === "note" ? v : Number(v); }
  const text = JSON.stringify(labels, null, 1);
  const out = document.getElementById("out"); out.value = text; out.select();
  try { await navigator.clipboard.writeText(text); } catch (e) {}
});
</script></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the blind human-labelling form")
    parser.add_argument("--per-config", type=int, default=4)
    parser.add_argument("--seed", type=int, default=3)
    args = parser.parse_args()
    items = pick_items(args.per_config, args.seed)
    (HERE / "label_form.html").write_text(render(items), encoding="utf-8")
    key = [
        {
            "item_id": it["item_id"],
            "scenario": it["scenario"]["id"],
            "config": it["config"],
            "judge": {d: it["row"]["judge"][d] for d in DIMENSIONS},
        }
        for it in items
    ]
    (HERE / "items.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
    print(f"{len(items)} items -> {HERE / 'label_form.html'}")


if __name__ == "__main__":
    main()
