FROM python:3.12-slim

WORKDIR /app

# System deps for passagemath-polyhedra runtime
# libgmp10 is the only runtime library needed — passagemath ships
# pre-compiled manylinux wheels with all native deps bundled.
# curl is needed to bootstrap the Rust toolchain for the IPC bridge.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgmp10 curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Rust toolchain (minimal profile) + maturin — builds the dual-chamber
# IPC bridge (PyO3 + memmap3) that gives LINA her nervous system.
ENV PATH="/root/.cargo/bin:${PATH}"
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal \
    && rustc --version

COPY ipc ./ipc
COPY ipc-core ./ipc-core
RUN pip install --no-cache-dir maturin \
    && cd ipc && maturin develop --release && cd ..

COPY . .

EXPOSE 8001

CMD ["uvicorn", "lina_service:app", "--host", "0.0.0.0", "--port", "8001"]
