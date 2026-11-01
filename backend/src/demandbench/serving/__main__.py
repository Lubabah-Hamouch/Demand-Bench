"""Run the API: python -m demandbench.serving [--host H] [--port N] [--reload].

The port comes from --port, else $PORT (set by hosts such as Render), else
$DEMANDBENCH_PORT, else 8020. The host comes from --host, else $DEMANDBENCH_HOST, else
127.0.0.1 (a container needs 0.0.0.0).
"""

import argparse
import os

import uvicorn

from demandbench.serving.app import DEFAULT_PORT


def default_port() -> int:
    return int(os.environ.get("PORT") or os.environ.get("DEMANDBENCH_PORT") or DEFAULT_PORT)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("DEMANDBENCH_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=default_port())
    parser.add_argument("--reload", action="store_true", help="restart on code changes")
    args = parser.parse_args()
    uvicorn.run("demandbench.serving.app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
