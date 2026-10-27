# Local Langfuse

Self-hosted [Langfuse](https://langfuse.com) for tracing the agents. The compose file is Langfuse's official one, with every port bound to `127.0.0.1`.

## Start

1. Create `infra/langfuse/.env` with random secrets and the `LANGFUSE_INIT_*` values (organisation, project, API keys, admin user), and put the same project keys in the repo's `.env` as `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` and `LANGFUSE_HOST=http://localhost:3000`. Both files are git-ignored.
2. `docker compose --env-file .env up -d` from this folder.
3. Open http://localhost:3000 and sign in with `LANGFUSE_INIT_USER_EMAIL` / `LANGFUSE_INIT_USER_PASSWORD`.

## What gets traced

One trace per agent run (session = thread id, tags = team, approval mode, devil's advocate on/off; metadata = the model behind each role):

- `chain` front-office: the whole run, request in, memo out
- `agent` per LangGraph node (router, gm_plan, stats, valuation, scout, cap, devils_advocate, approval, memo)
- `generation` per LLM call: model, prompt, reply, tokens, cost at the list prices in `config/models.yaml`
- `tool` per MCP call: arguments, result, errors

Tracing switches itself off when the keys are missing or `FRONT_OFFICE_TRACING=0`, so tests and the Docker app run without it.

This deployment runs Langfuse v4 in events-only mode: read traces back with `GET /api/public/v2/observations?traceId=...`, not the legacy `/api/public/traces` endpoint.

## Stop

`docker compose down` keeps the data volumes; add `-v` to delete them.
