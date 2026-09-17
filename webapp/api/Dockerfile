# Build context is the repository root (see webapp/docker-compose.yml).
FROM python:3.12-slim

WORKDIR /app

COPY webapp/api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Shared config/db/job code.
COPY webapp/common ./common
# The API references the bundled demo CSV by the same relative path the
# worker uses, purely for display/bookkeeping; it does not need the rest of
# inference/ (no torch/esm here).
COPY inference/examples ./inference/examples

COPY webapp/api/app ./app

ENV PYTHONPATH=/app
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
