FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    FRONT_OFFICE_CHECKPOINTS=/home/user/state/checkpoints.sqlite \
    FRONT_OFFICE_NEWS_CACHE=/home/user/state/news \
    PORT=8501

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
RUN uv sync --frozen --no-dev

RUN useradd -m -u 1000 user && mkdir -p /home/user/state && chown -R user /home/user/state
USER user

EXPOSE 8501 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
    CMD curl -fs "http://localhost:${PORT}/_stcore/health" || exit 1
CMD ["sh", "-c", "streamlit run app/streamlit_app.py --server.address=0.0.0.0 --server.port=${PORT}"]
