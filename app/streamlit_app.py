from __future__ import annotations

import logging
import os
from datetime import date

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from agents.toolbox import ToolBox
from app import session
from app.session import Run

load_dotenv()
logging.disable(logging.INFO)
DEMO_LIMIT = int(os.environ.get("FRONT_OFFICE_DEMO_LIMIT") or 0)

st.set_page_config(page_title="Front Office", page_icon="🏀", layout="wide")

EXAMPLES = {
    "Rim protector": "We need a rim-protecting center who can play now. Stay below the second apron and keep our 2029 first.",
    "Cheap shooting": "Find us a 3-and-D wing on a cheap contract without giving up any first-round picks.",
    "Rebuild": "We are rebuilding: move veterans over 30 for younger players with upside.",
    "Stats question": "Who led the NBA in assists per game in 2024-25 (minimum 50 games)?",
    "Player check": "Is Jalen Brunson worth his contract, and what is his outlook for 2026-27?",
}
AGENTS = {
    "router": ("🧭", "Router"),
    "gm": ("🧠", "GM"),
    "stats": ("📊", "Stats analyst"),
    "valuation": ("💵", "Valuation model"),
    "scout": ("📰", "Scout"),
    "cap": ("📐", "Cap analyst"),
    "devil's advocate": ("😈", "Devil's advocate"),
    "approval": ("✅", "You"),
    "stopped": ("⛔", "Stopped"),
}
STATUS = {"under_cap": "Under the cap", "over_cap": "Over the cap", "over_tax": "Over the tax",
          "over_first_apron": "Over the 1st apron", "over_second_apron": "Over the 2nd apron"}  # fmt: skip
ROLE_LABELS = {"router": "Router", "gm": "GM", "stats": "Stats analyst", "scout": "Scout",
               "devils_advocate": "Devil's advocate", "memo": "Memo writer", "single_agent": "Single agent"}  # fmt: skip
SEVERITY = {"high": "🔴", "medium": "🟠", "low": "🟡"}
VERDICT = {"keep": ("Keep", "green"), "revise": ("Revise", "orange"), "drop": ("Drop", "red")}


def money(v: float | None, signed: bool = False) -> str:
    if v is None:
        return "–"
    sign = "+" if signed and v > 0 else ("−" if v < 0 else "")
    return f"{sign}${abs(v) / 1e6:,.1f}M"


@st.cache_resource
def toolbox() -> ToolBox:
    return ToolBox()


@st.cache_data(ttl=3600)
def teams() -> dict[str, str]:
    rows = toolbox().call(
        "run_sql", query="SELECT abbreviation, full_name FROM teams ORDER BY full_name"
    )
    return {abbr: name for abbr, name in rows["rows"]}


@st.cache_data(ttl=3600)
def cap_sheet(team: str) -> dict:
    return toolbox().call("get_team_cap_sheet", team=team)


@st.cache_data(ttl=3600)
def draft_assets(team: str) -> dict:
    return toolbox().call("get_draft_assets", team=team)


def sidebar() -> tuple[str | None, str, bool]:
    with st.sidebar:
        st.header("Your front office")
        names = teams()
        team = st.selectbox(
            "Team",
            [None, *names],
            format_func=lambda a: "Let the router infer it" if a is None else f"{names[a]} ({a})",
            index=list(names).index("BOS") + 1 if "BOS" in names else 0,
        )
        trade_date = st.date_input("Trade date", value=date.today(), min_value=date(2026, 7, 1),
                                   max_value=date(2027, 6, 30), help="Rules such as the trade deadline and recently-signed players depend on it.")  # fmt: skip
        devils = st.toggle(
            "Devil's advocate review",
            value=True,
            help="A critic agent challenges every proposal before you see it.",
        )
        if not DEMO_LIMIT:
            with st.expander("Resume a thread"):
                thread = st.text_input("Thread id", placeholder="e.g. 3f9a1c2b")
                if st.button("Load", disabled=not thread):
                    loaded = session.load(thread.strip(), session.make_graph(devils), devils)
                    if loaded:
                        st.session_state.run = loaded
                        st.rerun()
                    st.error("No checkpoint for that thread.")
        if team:
            team_snapshot(team)
    return team, trade_date.isoformat(), devils


def team_snapshot(team: str) -> None:
    sheet = cap_sheet(team)
    st.divider()
    st.subheader(f"{team} · {sheet['season']}")
    c1, c2 = st.columns(2)
    c1.metric("Payroll", money(sheet["payroll"]))
    c2.metric("Status", STATUS.get(sheet["status"], sheet["status"]).replace("Over the ", ""))
    room = sheet["room_to"]
    c1.metric("Room to 1st apron", money(room["first_apron"]))
    c2.metric("Room to 2nd apron", money(room["second_apron"]))
    st.caption(
        f"{sheet['standard_contracts']} standard + {sheet['two_way_contracts']} two-way contracts · dead money {money(sheet['dead_money'])}"
    )
    roster = pd.DataFrame(
        [
            {
                "Player": p["name"] + (" 🩹" if p.get("injury") else ""),
                "Salary $M": p["salary"] / 1e6,
                "Through": p["contract_through"],
                "Proj WS": p["projected_ws"],
            }
            for p in sheet["roster"]
            if not p["two_way"]
        ]
    )
    st.dataframe(
        roster,
        hide_index=True,
        width="stretch",
        column_config={"Salary $M": st.column_config.NumberColumn(format="%.1f")},
    )
    picks = [p for p in draft_assets(team)["owned"] if p["round"] == 1]
    st.caption(
        "First-round picks: "
        + (", ".join(f"{p['year']} ({p['original_team']})" for p in picks) or "none")
    )


def event_line(text: str) -> str:
    head, _, rest = text.partition(":")
    icon, label = AGENTS.get(head.strip(), ("•", head.strip().title()))
    return f"{icon} **{label}** — {rest.strip()}" if rest else f"{icon} {text}"


def run_with_status(label: str, events) -> None:
    with st.status(label, expanded=True) as status:
        try:
            for e in events:
                st.markdown(event_line(e))
        except Exception as exc:
            status.update(label="Something went wrong", state="error")
            st.exception(exc)
            st.stop()
        status.update(label="Done", state="complete", expanded=False)
    st.rerun()


def ask(team: str | None, trade_date: str, devils: bool) -> None:
    st.markdown(
        "Describe what your team needs in plain language. Specialist agents search the warehouse, value players with "
        "the projection model, read the news, build packages that the CBA rules engine certifies, and argue against "
        "them. Nothing is final until you approve it."
    )
    used = st.session_state.get("requests", 0)
    if DEMO_LIMIT and used >= DEMO_LIMIT:
        st.info(
            f"This public demo allows {DEMO_LIMIT} requests per session. Run it locally for more."
        )
        return
    choice = st.pills("Try an example", list(EXAMPLES), selection_mode="single")
    with st.form("ask"):
        request = st.text_area(
            "Request",
            value=EXAMPLES.get(choice, ""),
            height=110,
            placeholder="We need a starting-calibre point guard but must stay below the first apron…",
        )
        go = st.form_submit_button("Ask the front office", type="primary")
    if go and request.strip():
        st.session_state.requests = used + 1
        run = Run(request=request.strip(), team=team, devils_advocate=devils)
        st.session_state.run = run
        run_with_status(
            "Agents at work…",
            session.start(run, session.make_graph(devils), trade_date),
        )


def payroll_rows(validation: dict) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Team": t["team"],
                "Payroll before": money(t["payroll_before"]),
                "Payroll after": money(t["payroll_after"]),
                "Status after": STATUS.get(t["status_after"], t["status_after"]),
                "Out → In": f"{money(t['outgoing_salary'])} → {money(t['incoming_salary'])}",
                "Max incoming": money(t["max_incoming_salary"]),
                "Roster after": t["standard_roster_after"],
                "Hard cap": (t["hard_cap"] or "–").replace("_", " "),
            }
            for t in validation["teams"]
        ]
    )


def proposal_card(
    p: dict, critique: dict | None, selectable: bool, approved: bool | None = None
) -> bool:
    with st.container(border=True):
        top = st.columns([5, 2])
        r = p["receive"]
        top[0].markdown(f"#### {p['id']} · {r['name']} from {p['from_team']}")
        if critique:
            text, color = VERDICT[critique["verdict"]]
            top[1].badge(f"Devil's advocate: {text}", color=color)
        if approved is not None:
            top[1].badge(
                "Approved" if approved else "Not approved", color="green" if approved else "gray"
            )
        send = (
            ", ".join(f"{s['name']} ({money(s['salary'])})" for s in p["send_players"])
            or "no players"
        )
        picks = ", ".join(x["asset_id"] for x in p["send_picks"]) or "no picks"
        st.markdown(
            f"**We receive** {r['name']} ({money(r['salary'])}, projected {r['projected_ws']:.1f} WS)  \n"
            f"**We send** {send} · {picks}"
        )
        v = p["value"]
        m = st.columns(4)
        m[0].metric("Win Shares for us", f"{v['ws_change_for_us']:+.1f}")
        m[1].metric("Our contract value", money(v["our_value_change"], signed=True))
        m[2].metric("Their contract value", money(v["counterparty_value_change"], signed=True))
        m[3].metric("Rules engine", "Legal" if p["validation"]["valid"] else "Illegal")
        st.dataframe(payroll_rows(p["validation"]), hide_index=True, width="stretch")
        for w in p["validation"].get("warnings", []):
            st.caption(f"⚠️ {w}")
        if critique:
            with st.expander("Devil's advocate", expanded=critique["verdict"] != "keep"):
                st.write(critique["reasoning"])
                for c in critique.get("concerns", []):
                    st.markdown(f"{SEVERITY.get(c['severity'], '•')} {c['issue']}")
                st.caption(
                    "Counterparty would likely accept"
                    if critique["counterparty_would_accept"]
                    else "Counterparty would likely refuse"
                )
        if selectable:
            return st.checkbox(f"Approve {p['id']}", key=f"approve_{p['id']}")
    return False


def approval(run: Run) -> None:
    pending = run.pending
    proposals = pending.get("proposals", [])
    crit = {c["proposal_id"]: c for c in pending.get("critiques", [])}
    st.subheader("Proposals awaiting your approval")
    st.caption(
        "Every package below passed the CBA rules engine. Pre-selected: the ones the devil's advocate did not drop."
    )
    if not proposals:
        st.info("No legal package satisfied the brief. Continue to get a memo explaining why.")
    defaults = session.default_selection(pending)
    for p in proposals:
        st.session_state.setdefault(f"approve_{p['id']}", p["id"] in defaults)
    chosen = [p["id"] for p in proposals if proposal_card(p, crit.get(p["id"]), selectable=True)]
    notes = st.text_area(
        "Notes for the memo (optional)",
        placeholder="e.g. Ownership prefers not to add salary next season.",
    )
    c1, c2, _ = st.columns([2, 2, 5])
    if c1.button(f"Approve {len(chosen)} and write memo", type="primary"):
        decision = chosen
    elif c2.button("Reject all"):
        decision = []
    else:
        return
    run_with_status(
        "Writing the memo…",
        session.resume(run, session.make_graph(run.devils_advocate), decision, notes),
    )


def outcomes(state: dict) -> None:
    rows = [{"Target": k, "Outcome": v} for k, v in state.get("target_outcomes", {}).items()]
    if rows:
        st.markdown("**Why other targets were not proposed**")
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def cost_panel(state: dict, run: Run) -> None:
    report = session.costs(state)
    t = report["total"]
    c = st.columns(4)
    c[0].metric("LLM calls", t["calls"])
    c[1].metric("Tokens", f"{t['input_tokens'] + t['output_tokens']:,}")
    c[2].metric("Model time", f"{t['seconds']:.0f}s")
    c[3].metric("At list prices", f"${t['usd']:.4f}")
    roles = pd.DataFrame(
        [
            {"Agent": ROLE_LABELS.get(r, r), "Calls": v["calls"], "Input tokens": v["input_tokens"],
             "Output tokens": v["output_tokens"], "Seconds": v["seconds"], "USD": v["usd"]}
            for r, v in report["by_role"].items()
        ]
    )  # fmt: skip
    if not roles.empty:
        st.bar_chart(roles, x="Agent", y="Seconds", horizontal=True, height=220)
        st.dataframe(roles, hide_index=True, width="stretch",
                     column_config={"USD": st.column_config.NumberColumn(format="$%.5f")})  # fmt: skip
    calls = state.get("tool_calls", [])
    if calls:
        tools = (
            pd.DataFrame(calls)
            .groupby("tool")
            .agg(Calls=("tool", "size"), Seconds=("seconds", "sum"), Errors=("error", "sum"))
        )
        st.markdown("**MCP tool calls**")
        st.dataframe(
            tools.reset_index().rename(columns={"tool": "Tool"}), hide_index=True, width="stretch"
        )
    for tid in run.trace_ids:
        st.link_button("Open trace in Langfuse", session.trace_url(tid))


def sql_panel(state: dict) -> None:
    for a in state.get("sql_attempts", []):
        label = f"Attempt {a['attempt']} · {'ok' if a['ok'] else 'rejected'}"
        with st.expander(label, expanded=False):
            st.code(a["sql"], language="sql")
            if a.get("problem"):
                st.error(a["problem"])


def result(run: Run) -> None:
    state = run.state
    if state.get("error"):
        st.warning(state["error"])
    tabs = st.tabs(
        ["Answer" if state.get("answer") else "Memo", "Proposals", "Agent steps", "Cost & latency"]
    )
    with tabs[0]:
        text = state.get("memo") or state.get("answer") or ""
        if text:
            st.markdown(text)
            st.download_button("Download memo (Markdown)", text, file_name=f"front-office-{run.thread}.md",
                               mime="text/markdown")  # fmt: skip
    with tabs[1]:
        approved = set((state.get("approval") or {}).get("approved", []))
        crit = {c["proposal_id"]: c for c in state.get("critiques", [])}
        for p in state.get("proposals", []):
            proposal_card(p, crit.get(p["id"]), selectable=False, approved=p["id"] in approved)
        if not state.get("proposals"):
            st.caption("No trade proposals in this run.")
        outcomes(state)
    with tabs[2]:
        for e in run.events:
            st.markdown(event_line(e))
        if state.get("goal"):
            with st.expander("Brief the GM extracted"):
                st.json(state["goal"])
        if state.get("sql_attempts"):
            st.markdown("**Text-to-SQL attempts**")
            sql_panel(state)
        if state.get("scouting"):
            with st.expander("Scout reports"):
                st.json(state["scouting"])
    with tabs[3]:
        cost_panel(state, run)


def main() -> None:
    team, trade_date, devils = sidebar()
    st.title("🏀 Front Office")
    st.caption("A team of AI analysts that proposes CBA-legal NBA trades. You are the GM.")
    run: Run | None = st.session_state.get("run")
    if run is None:
        ask(team, trade_date, devils)
        return
    head = st.columns([6, 1])
    head[0].markdown(f"> {run.request}")
    head[0].caption(f"Thread `{run.thread}` · team {run.team or 'inferred'}")
    if head[1].button("New request"):
        for k in [k for k in st.session_state if k.startswith("approve_")] + ["run"]:
            del st.session_state[k]
        st.rerun()
    if run.pending is not None:
        with st.expander("Agent steps so far"):
            for e in run.events:
                st.markdown(event_line(e))
        approval(run)
    else:
        result(run)


main()
