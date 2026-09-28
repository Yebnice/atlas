#!/usr/bin/env python3
import sys
import urllib.request

base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
for path in ("/healthz", "/readyz", "/metrics"):
    with urllib.request.urlopen(base + path, timeout=5) as r:
        print(path, r.status, r.read(200).decode(errors="replace"))
