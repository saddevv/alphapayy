FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8090 \
    WEB_CONCURRENCY=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY graph_agent ./graph_agent
COPY graph_standalone_app ./graph_standalone_app
COPY utils ./utils

USER app

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.getenv('PORT', '8090'), timeout=3).read()"

CMD ["sh", "-c", "uvicorn graph_standalone_app.server:app --host 0.0.0.0 --port ${PORT:-8090} --workers ${WEB_CONCURRENCY:-1}"]
