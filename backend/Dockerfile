FROM python:3.11-slim

WORKDIR /app

# System deps needed by pymavlink and asyncpg
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# --timeout/--retries guard against PyPI read timeouts on large wheels
# (qiskit-aer, opencv-python-headless, ...) over a slow/unstable connection.
RUN pip install --no-cache-dir --timeout 120 --retries 10 -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]