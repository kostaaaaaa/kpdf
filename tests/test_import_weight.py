"""Startup-time regression guards: importing kpdf must stay cheap."""

import os
import subprocess
import sys


def _run(code: str) -> str:
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True
    )
    return out.stdout.strip()


def test_import_does_not_pull_onnx_stack():
    assert _run("import kpdf, sys; print('onnxruntime' in sys.modules)") == "False"
