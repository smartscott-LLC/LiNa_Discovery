"""TritonService lifecycle tests — the Rust spoke, managed by the loop.

The spoke must be spawned and stopped by the entrypoint, and a missing
binary must be honest (alive=False) rather than a crash. Tests run inside
a real aiomisc entrypoint, the way she runs in production.
"""
import os
import sys
import tempfile

sys.path.insert(0, "/home/server/LiNa_Discovery/backend/lina")

from aiomisc import entrypoint  # noqa: E402

from lina_service import TritonService, _find_triton_binary  # noqa: E402


def _fake_triton_script(tmp):
    path = os.path.join(tmp, "fake-triton.sh")
    with open(path, "w") as fh:
        fh.write("#!/bin/sh\nsleep 60\n")
    os.chmod(path, 0o755)
    return path


def test_triton_service_spawns_and_stops():
    with tempfile.TemporaryDirectory() as tmp:
        svc = TritonService(binary=_fake_triton_script(tmp))
        with entrypoint(svc):
            assert svc.alive is True
            assert svc.proc is not None
        assert svc.proc is None
        assert svc.alive is False


def test_triton_service_missing_binary_is_honest():
    svc = TritonService(binary="/nonexistent/triton-binary")
    with entrypoint(svc):
        assert svc.alive is False
        assert svc.proc is None


def test_find_triton_binary_resolves():
    found = _find_triton_binary()
    if found:
        assert os.path.isfile(found), found
