import sys

try:
    from .main import run

    code = run()
except ModuleNotFoundError as error:
    # A venv synced before uv.lock gained a dependency fails here, or at a lazy import inside
    # run(), until setup syncs it.
    package = (error.name or "a dependency").partition(".")[0]
    print(f"omafindd cannot import {package}. Run bin/omafind setup.", file=sys.stderr)
    code = 1
raise SystemExit(code)
