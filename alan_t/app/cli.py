"""`alan` CLI — bootstrap sanity checks (INFRASTRUCTURE.md §6)."""

from __future__ import annotations

import argparse
import asyncio
import sys


def main() -> None:
    parser = argparse.ArgumentParser(prog="alan")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("bootstrap", help="sanity-check config + DB connectivity")
    args = parser.parse_args()

    if args.cmd == "bootstrap":
        sys.exit(asyncio.run(_bootstrap()))


async def _bootstrap() -> int:
    from alan_t.app.bootstrap import build

    app = build()
    problems = []
    if not app.settings.alan_api_token:
        problems.append("ALAN_API_TOKEN is empty")
    if not app.settings.groq_api_key:
        problems.append("GROQ_API_KEY is empty (primary CHAT provider)")
    if not app.settings.google_api_key:
        problems.append("GOOGLE_API_KEY is empty (embeddings + fallback)")
    try:
        await app.store.list_sessions()
        print("postgres: ok")
    except Exception as e:
        problems.append(f"postgres unreachable: {e}")
    print(f"models: {app.router.active_models()}")
    for p in problems:
        print(f"WARN: {p}")
    return 1 if problems else 0
