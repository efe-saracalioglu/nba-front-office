# Front Office

A multi-agent NBA front office: give it a goal ("we want a star center, here's our budget, protect our future picks") and it returns CBA-compliant trade proposals, statistical and financial rationale, risks and counter-arguments, and an executive memo.

> Work in progress. The demo, architecture diagram, eval results and design decisions land here as each phase ships.

## Development

```bash
uv sync --group dev
uv run pytest
uv run ruff check .
```

Copy `.env.example` to `.env` and fill in `ANTHROPIC_API_KEY`.
