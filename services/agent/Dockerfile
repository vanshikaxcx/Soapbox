FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

WORKDIR /app

# Lightpanda: the Zepto connector's browser engine (see services/merchants/
# browser_pool.py). Blinkit stays on the bundled Chromium above — it needs a
# real browser TLS fingerprint to get past Blinkit's Cloudflare bot check,
# which Lightpanda deliberately does not impersonate.
RUN curl -fsSL -o /usr/local/bin/lightpanda \
        https://github.com/lightpanda-io/browser/releases/download/nightly/lightpanda-x86_64-linux \
    && chmod +x /usr/local/bin/lightpanda

COPY services/agent/requirements.txt services/agent/requirements.txt
RUN pip install --no-cache-dir -r services/agent/requirements.txt

COPY services/agent services/agent
COPY services/merchants services/merchants

ENV PYTHONPATH=/app
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

CMD ["uvicorn", "services.agent.main:app", "--host", "0.0.0.0", "--port", "8080"]
