#!/usr/bin/env python3
"""Generate the production whitelist fingerprint for one withdrawal destination."""
import argparse
from app.withdrawal_security import destination_fingerprint
p=argparse.ArgumentParser()
p.add_argument('--currency', required=True)
p.add_argument('--destination', required=True)
p.add_argument('--network', default='')
a=p.parse_args()
print(destination_fingerprint(a.destination, a.currency, a.network))
