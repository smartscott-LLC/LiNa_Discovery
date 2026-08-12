FROM python:3.12-slim

WORKDIR /app

# System deps for passagemath-polyhedra runtime and Rust build scripts.
# libgmp10 is the only runtime library needed for passagemath; build-essential
# provides the C linker (cc) required by cargo build scripts.
# curl is needed to bootstrap the Rust toolchain for the Triton spoke.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgmp10 curl build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY backend/lina/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Rust toolchain (minimal profile) — builds Triton, the Rust spoke that
# attaches to LINA's shared-memory chambers (no PyO3, no maturin).
ENV PATH="/root/.cargo/bin:${PATH}"
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal \
    && rustc --version

# Shared Rust core + Triton consumer (the spoke).
COPY backend/ipc-core ./ipc-core
COPY backend/triton ./triton
RUN cd triton && cargo build --release \
       && cp target/release/triton /usr/local/bin/triton \
       && cd ..

# LINA identity service (entrypoint: python -m lina_service).
COPY backend/lina/ .
# PWA shell (Phase 3) — her interface, served by her own service at /pwa.
COPY backend/pwa/ ./pwa
# Her theme — the color scheme, yours to own, served at /assets.
COPY assets/ ./assets

EXPOSE 8001

# aiomisc entrypoint — starts the voice pool, IPC chambers, and the
# uvicorn server under one unified lifecycle.
CMD ["python", "-m", "lina_service"]
