# ── builder ────────────────────────────────────────────────────────────────────
# Compiles C-extension wheels (asyncpg, numba/llvmlite) and installs runtime
# deps only into /install.  Build tools stay in this layer and are never
# copied to the final image.
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml .
# Stub the package so setuptools can resolve the project without full source.
RUN mkdir -p app && touch app/__init__.py
RUN pip install --no-cache-dir --prefix=/install .

# ── runtime ────────────────────────────────────────────────────────────────────
# Lean production image: no build tools, no dev packages.
FROM python:3.12-slim AS runtime

# libpq5   — asyncpg runtime dependency
# libgomp1 — numba OpenMP runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

COPY --from=builder /install /usr/local

COPY . .

RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
