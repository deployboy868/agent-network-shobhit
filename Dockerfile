# Agent Social Network — Teams API + Streamlit demo UI
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PORT=3978 \
    TWIN_MEMORY_DB=/data/twin-memory.db \
    TWIN_AUDIT_LOG=/data/twin-audit.jsonl

WORKDIR /app

COPY requirements-docker.txt ./
RUN pip install --no-cache-dir -r requirements-docker.txt

COPY agent_network ./agent_network
COPY scripts/docker-entrypoint.sh ./scripts/docker-entrypoint.sh

RUN mkdir -p /data \
    && useradd --create-home --uid 1000 appuser \
    && chmod +x /app/scripts/docker-entrypoint.sh \
    && chown -R appuser:appuser /app /data

USER appuser

EXPOSE 3978 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3978/healthz', timeout=3)"

# Demo UI: http://localhost:8501  |  Teams API: POST /api/messages  |  GET /healthz
CMD ["/app/scripts/docker-entrypoint.sh"]
