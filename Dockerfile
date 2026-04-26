FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir . \
    && pip uninstall -y pip setuptools wheel

USER app

ENV TRANSPORT=http \
    HOST=0.0.0.0 \
    PORT=8000

EXPOSE 8000

CMD ["cwmcp-http"]
