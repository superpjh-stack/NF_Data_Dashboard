"""Reload only the NeedsFood TLS gateway when the shared certificate rotates."""
import hashlib
import os
from pathlib import Path
import subprocess

ROOT=Path('/docker/nf-data-dashboard')

def main():
    os.umask(0o077)
    env=dict(line.split('=',1) for line in (ROOT/'.env').read_text().splitlines() if '=' in line)
    certs=Path(env['TLS_DIRECTORY'])
    fingerprint=hashlib.sha256(b''.join((certs/('srv1934103.hstgr.cloud.'+suffix)).read_bytes() for suffix in ('crt','key'))).hexdigest()
    state=ROOT/'.tls-fingerprint'
    if state.exists() and state.read_text()==fingerprint:return
    subprocess.run(['docker','exec','nf-data-dashboard-gateway','nginx','-t'],check=True)
    subprocess.run(['docker','exec','nf-data-dashboard-gateway','nginx','-s','reload'],check=True)
    state.write_text(fingerprint)
    print('NeedsFood gateway TLS certificate reloaded.')

if __name__=='__main__':main()
