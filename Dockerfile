FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir \
    "binance>=0.3.109" \
    "cryptography>=48.0.0" \
    "numpy>=2.4.6" \
    "pandas>=3.0.3" \
    "python-binance>=1.0.36"

COPY *.py ./
RUN mkdir -p logs

CMD ["python3", "-u", "main.py"]
