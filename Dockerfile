# syntax=docker/dockerfile:1
FROM python:3.13-slim AS builder

WORKDIR /app

# RUN apt-get update && apt-get install -y --no-install-recommends \
#     gcc \
#     libpq-dev \
#     && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# --no-cache-dir
RUN pip install --user -r requirements.txt

FROM python:3.13-slim

WORKDIR /app

COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

RUN mkdir -p /app/uploads

COPY . .

CMD ["python", "src/main.py"]
