# Front Office MCP server

A standalone [Model Context Protocol](https://modelcontextprotocol.io) server that gives any MCP client (Claude Desktop, Cursor, your own agents) the project's NBA data, the CBA trade rules engine and the player valuation model. Every tool is read-only.

## Tools

| Tool | What it answers |
|---|---|
| `search_players` | Who is "Jackson"? Rostered players by partial name, with team and salary |
| `describe_schema` | What tables and columns exist, with units and conventions |
| `run_sql` | Any stats question, as one read-only `SELECT` (200-row cap, 15 s timeout) |
| `get_team_cap_sheet` | A team's payroll, distance to the cap, tax line and aprons, roster, picks |
| `validate_trade` | Is this trade legal under the 2023 CBA, and why not? |
| `find_salary_matches` | Which player packages could a team legally send for a target player? |
| `predict_player_value` | Projected 2026-27 Win Shares with an 80% interval, surplus value, SHAP factors |
| `get_draft_assets` | Picks a team owns, its own picks held by others, swap rights |
| `get_player_news` | Injury status and ESPN headlines, marked as untrusted external text |

Resources: `frontoffice://schema` (DDL with column notes), `frontoffice://sql-examples` (worked queries for text-to-SQL), `frontoffice://cba-rules` (2026-27 figures and the rules the engine enforces).

## Run it

```bash
python -m uv run python -m mcp_server.server                      # stdio
python -m uv run python -m mcp_server.server --transport http     # http://127.0.0.1:8765/mcp
```

The server reads `FRONT_OFFICE_DB` if set, otherwise `data/warehouse.duckdb`, and falls back to the bundled sample warehouse (`data/sample/warehouse_sample.duckdb`), so it works from a fresh clone.

## Connect Claude Desktop

Add this to `claude_desktop_config.json` (Windows: `%APPDATA%\Claude\`, macOS: `~/Library/Application Support/Claude/`) and restart Claude Desktop:

```json
{
  "mcpServers": {
    "front-office": {
      "command": "python",
      "args": ["-m", "uv", "--directory", "C:/path/to/nba-front-office", "run", "python", "-m", "mcp_server.server"]
    }
  }
}
```

Then ask, for example: *"Can Boston trade for Victor Wembanyama without giving up picks? Check it with the rules engine."*

## Safety

- The database is opened read-only with external file access disabled and the configuration locked, and `run_sql` accepts exactly one `SELECT`.
- `get_player_news` returns text from external websites with a notice to treat it as data. Set `FRONT_OFFICE_NEWS_FIXTURES` to a folder with `articles.json` and `injuries.json` to serve fixed pages instead, which the prompt-injection evals use.
