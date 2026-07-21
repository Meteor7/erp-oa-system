FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONWARNINGS=ignore::DeprecationWarning \
    PADDLE_PDX_MODEL_SOURCE=BOS \
    HOME=/models \
    XDG_CACHE_HOME=/models/.cache \
    PADDLE_HOME=/models/.paddle

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgomp1 \
        libglib2.0-0 \
        libgl1 \
        libsm6 \
        libxext6 \
        libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt

RUN groupadd --system ocr \
    && useradd --system --gid ocr --home-dir /models ocr \
    && mkdir -p /models \
    && chown -R ocr:ocr /models

COPY --chown=ocr:ocr pyproject.toml ./
COPY --chown=ocr:ocr invoice_ocr ./invoice_ocr

USER ocr
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=120s --start-period=180s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/ready', timeout=110).read()"]
CMD ["uvicorn", "invoice_ocr.api:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]


FROM runtime AS test

USER root
COPY requirements-test.txt ./
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements-test.txt
COPY --chown=ocr:ocr tests ./tests
COPY --chown=ocr:ocr Dockerfile .dockerignore ./
USER ocr
CMD ["python", "-m", "pytest", "-q"]
