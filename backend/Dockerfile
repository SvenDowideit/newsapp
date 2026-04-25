FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .
RUN playwright install chromium --with-deps || true

COPY newsagg/ newsagg/
COPY migrations/ migrations/

EXPOSE 8000

ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "newsagg.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
