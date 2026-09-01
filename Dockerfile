# Basis container.
# Single stage: the app is pure Python with no build step and no node_modules.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY web ./web
COPY scripts ./scripts

# The disk cache holds public API responses only, never applicant data. It is
# fine for it to be ephemeral: a cold cache costs a few seconds on first request.
RUN mkdir -p /app/.cache && \
    adduser --disabled-password --gecos "" --uid 10001 app && \
    chown -R app:app /app
USER app

EXPOSE 8767

# Hosts inject the port they want. Default matches local development.
ENV PORT=8767

HEALTHCHECK --interval=60s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8767')+'/health').read()" || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8767} --proxy-headers --forwarded-allow-ips='*'"]
