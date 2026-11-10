# ResearchMind 2.0 API. Python 3.13 is the verified backend runtime.
# The image does not copy .env. Inject DATABASE_URL and provider keys at run time.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app \
    WEB_CONCURRENCY=1 \
    PORT=8000

WORKDIR /app

COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm -rf /tmp/requirements.txt \
    && useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin app

COPY --chown=app:app backend /app/backend
# Read by backend/app/api/v1/mcp_reads.py at /app/docs/evals/published-summary.json.
COPY --chown=app:app docs/evals/published-summary.json /app/docs/evals/published-summary.json
COPY --chown=app:app infra/docker-entrypoint.sh /app/infra/docker-entrypoint.sh
RUN chmod 755 /app/infra/docker-entrypoint.sh

USER app

EXPOSE 8000

# No HEALTHCHECK: Render uses healthCheckPath in render.yaml and ignores it.
CMD ["/app/infra/docker-entrypoint.sh"]
