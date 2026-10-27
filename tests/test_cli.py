import os
import subprocess
import sys

ENV = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}


def kpdf(*args):
    return subprocess.run(
        [sys.executable, "-m", "kpdf", *args], capture_output=True, text=True, env=ENV
    )


def test_help_lists_keys():
    r = kpdf("--help")
    assert r.returncode == 0
    assert "Enter" in r.stdout and "follow the selected link" in r.stdout


def test_version():
    r = kpdf("--version")
    assert r.returncode == 0
    assert r.stdout.startswith("kpdf ")


def test_no_args_is_an_error():
    assert kpdf().returncode == 1


def test_missing_file_message():
    r = kpdf("/definitely/not/here.pdf")
    assert r.returncode != 0
    assert "no such file" in r.stderr
