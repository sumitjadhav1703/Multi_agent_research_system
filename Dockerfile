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
COPY backend/requirements-fetch.txt /tmp/requirements-fetch.txt
# langchain 1.4.7 depends on langgraph>=1.2.12. The API pins langgraph==1.1.10.
# Install the fetch extras without dependencies so that pin is not replaced.
# beautifulsoup4, tavily-python, and langchain import libraries already present
# in backend/requirements.txt (typing-extensions, requests, httpx, tiktoken,
# langchain-core). soupsieve is pinned beside beautifulsoup4.
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && pip install --no-cache-dir --no-deps -r /tmp/requirements-fetch.txt \
    && rm -rf /tmp/requirements.txt /tmp/requirements-fetch.txt \
    && useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin app

COPY --chown=app:app backend /app/backend
COPY --chown=app:app tools.py /app/tools.py
COPY --chown=app:app infra/docker-entrypoint.sh /app/infra/docker-entrypoint.sh
RUN chmod 755 /app/infra/docker-entrypoint.sh

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/api/v1/health/live', timeout=3)"

CMD ["/app/infra/docker-entrypoint.sh"]
