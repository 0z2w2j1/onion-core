FROM python:3.11-slim AS base

WORKDIR /app

RUN pip install --no-cache-dir pip setuptools wheel

COPY pyproject.toml .
RUN pip install --no-cache-dir "onion-core[openai,anthropic,domestic,otel,prometheus] @ ." || \
    pip install --no-cache-dir ".[openai,anthropic,domestic,otel,prometheus]"

COPY onion_core/ ./onion_core/
COPY examples/ ./examples/

EXPOSE 8000

ENTRYPOINT ["python"]
