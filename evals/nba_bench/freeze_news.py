from __future__ import annotations

import json
from pathlib import Path

from data.config import RAW_DIR
from mcp_server.warehouse import connect

OUT = Path(__file__).resolve().parent / "news_fixtures"


def main() -> None:
    con = connect()
    rows = con.execute(
        """SELECT r.player_name, t.full_name, i.status, i.report_date, i.description, i.source
           FROM injuries i JOIN rosters r USING (player_id) JOIN teams t ON t.team_id = r.team_id"""
    ).fetchall()
    con.close()
    injuries = [{"player_name": n, "team": t, "status": s, "date": str(d), "comment": c, "detail": c, "source": src}
                for n, t, s, d, c, src in rows]  # fmt: skip
    cached = RAW_DIR / "news" / "espn_articles.json"
    articles = json.loads(cached.read_text(encoding="utf-8")) if cached.exists() else []
    OUT.mkdir(exist_ok=True)
    (OUT / "injuries.json").write_text(
        json.dumps(injuries, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (OUT / "articles.json").write_text(
        json.dumps(articles, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"froze {len(injuries)} injury reports and {len(articles)} articles into {OUT}")


if __name__ == "__main__":
    main()
