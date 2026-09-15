FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

WORKDIR /app

COPY services/agent/requirements.txt services/agent/requirements.txt
RUN pip install --no-cache-dir -r services/agent/requirements.txt

COPY services/agent services/agent
COPY services/merchants services/merchants

ENV PYTHONPATH=/app
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

CMD ["uvicorn", "services.agent.main:app", "--host", "0.0.0.0", "--port", "8080"]
