import sys
import traceback

from . import startlog

try:
    from .main import run

    code = run()
except ModuleNotFoundError as error:
    # A venv synced before uv.lock gained a dependency fails here, or at a lazy import inside
    # run(), until setup syncs it.
    package = (error.name or "a dependency").partition(".")[0]
    message = f"omafindd cannot import {package}. Run bin/omafind setup."
    print(message, file=sys.stderr)
    startlog.write(message)
    code = 1
except Exception:
    startlog.write(traceback.format_exc())
    raise
raise SystemExit(code)
