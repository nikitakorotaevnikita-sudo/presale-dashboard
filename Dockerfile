FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PRESALE_DB=/app/data/presale.db

# Исходники и статика копируются до установки, чтобы setuptools
# обнаружил пакет src при сборке. Chart.js лежит локально в static/vendor
# (без CDN) — образ работает офлайн.
COPY pyproject.toml ./
COPY src ./src
COPY static ./static

RUN pip install --no-cache-dir . && mkdir -p /app/data

EXPOSE 8090

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8090"]
