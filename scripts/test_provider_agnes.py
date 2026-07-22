"""Connectivity test for the 'agnes' provider. See scripts/test_all_providers.py."""
from __future__ import annotations
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import asyncio
from test_all_providers import main

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main("agnes")))
