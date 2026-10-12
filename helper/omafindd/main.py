import asyncio
import logging
import os
import signal
from pathlib import Path

from . import paths
from .ipc import AlreadyRunning, IpcServer
from .state import State

logger = logging.getLogger(__name__)


async def _serve(manifest: Path | None = None, *, interval: float = 0.5) -> int:
    manifest = manifest if manifest is not None else paths.manifest_path()
    if not manifest.is_file():
        return 0
    paths.data_dir()
    server = IpcServer(paths.socket_path())
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    signals = (signal.SIGINT, signal.SIGTERM)
    for signum in signals:
        loop.add_signal_handler(signum, stop.set)
    try:
        await server.start()
        while manifest.is_file() and not stop.is_set():
            detected = State.detect()
            await server.state.update(runtime=detected.runtime, model=detected.model)
            try:
                await asyncio.wait_for(stop.wait(), interval)
            except TimeoutError:
                pass
        return 0
    except AlreadyRunning as error:
        logger.error("%s", error)
        return 1
    finally:
        await server.stop()
        for signum in signals:
            loop.remove_signal_handler(signum)


def run() -> int:
    level = os.environ.get("OMAFINDD_LOG", "INFO").upper()
    logging.basicConfig(level=level if level in logging.getLevelNamesMapping() else "INFO")
    try:
        return asyncio.run(_serve())
    except (OSError, ValueError) as error:
        logger.error("%s", error)
        return 1
    except KeyboardInterrupt:
        return 0
