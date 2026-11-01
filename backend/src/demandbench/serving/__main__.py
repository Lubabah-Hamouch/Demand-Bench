"""Run the API: python -m demandbench.serving [--port N] [--reload]."""

import argparse
import os

import uvicorn

from demandbench.serving.app import DEFAULT_PORT


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("DEMANDBENCH_PORT", DEFAULT_PORT))
    )
    parser.add_argument("--reload", action="store_true", help="restart on code changes")
    args = parser.parse_args()
    uvicorn.run("demandbench.serving.app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
