"""Minimal .env loader so every entry point (manage.py, WSGI, ASGI) sees the same config."""

import os
from pathlib import Path


def load_env_file(path):
    """Load KEY=VALUE pairs from path without overriding real environment variables."""
    env_path = Path(path)
    if not env_path.is_file():
        return

    try:
        lines = env_path.read_text(encoding='utf-8').splitlines()
    except OSError:
        return

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[len('export '):].lstrip()
        if '=' not in line:
            continue

        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        os.environ.setdefault(key, value)
