"""Fail the build on the bug classes that shipped in 3.10.45: undefined names and shadowed imports."""
import subprocess
import sys


def _pyflakes():
    out = subprocess.run([sys.executable, "-m", "pyflakes", "app"], capture_output=True, text=True).stdout
    return out.splitlines()


def test_no_undefined_names():
    bad = [l for l in _pyflakes() if "undefined name" in l]
    assert not bad, "\n".join(bad)


def test_no_shadowed_route_or_import_redefinitions():
    bad = [l for l in _pyflakes() if "redefinition of unused" in l and "base64" not in l]
    assert not bad, "\n".join(bad)


def test_portal_pages_and_static_render():
    from fastapi.testclient import TestClient
    import app.main as main
    client = TestClient(main.app)
    for path in ("/", "/admin", "/static/customer.css"):
        assert client.get(path).status_code == 200, path
