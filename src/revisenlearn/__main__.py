"""``python -m revisenlearn`` — server, or server plus desktop window."""

from __future__ import annotations

import argparse
import logging

from . import config


def main() -> int:
    parser = argparse.ArgumentParser(prog="revisenlearn")
    parser.add_argument("--server", action="store_true",
                        help="backend only, no desktop window")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    if args.port:
        import os
        os.environ["RNL_PORT"] = str(args.port)

    logging.basicConfig(level=logging.INFO)

    if args.server:
        import uvicorn
        uvicorn.run("revisenlearn.main:app", host=config.HOST, port=config.port())
        return 0

    from .desktop import run_desktop
    return run_desktop()


if __name__ == "__main__":
    raise SystemExit(main())
