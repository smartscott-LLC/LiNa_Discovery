FROM python:3.12-slim

WORKDIR /app

# System deps for passagemath-polyhedra runtime and Rust build scripts.
# libgmp10 is the only runtime library needed for passagemath; build-essential
# provides the C linker (cc) required by cargo build scripts.
# curl is needed to bootstrap the Rust toolchain for the IPC bridge.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgmp10 curl build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY lina/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Rust toolchain (minimal profile) + maturin — builds the dual-chamber
# IPC bridge (PyO3 + memmap3) that gives LINA her nervous system.
ENV PATH="/root/.cargo/bin:${PATH}"
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal \
    && rustc --version

# Shared Rust core + PyO3 bridge + Triton consumer.
COPY ipc-core ./ipc-core
COPY ipc ./ipc
COPY triton ./triton
RUN pip install --no-cache-dir maturin \
    && cd ipc && maturin build --release -o /tmp/wheels && cd .. \
    && pip install --no-cache-dir /tmp/wheels/ipc_bridge-*.whl \
    && rm -rf /tmp/wheels \
    && cd triton && cargo build --release \
       && cp target/release/triton /usr/local/bin/triton \
       && cd ..

# LINA identity service (entrypoint: python -m lina_service).
COPY lina/ .

EXPOSE 8001

# aiomisc entrypoint — starts the voice pool, IPC bridge, and the
# uvicorn server under one unified lifecycle.
CMD ["python", "-m", "lina_service"]
