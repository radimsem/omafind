import asyncio
import logging
import os
import signal
from pathlib import Path

from . import paths
from .embedder import Embedder
from .embedding import Adapter
from .ipc import AlreadyRunning, IpcServer
from .service import SearchService
from .settings import SettingsReader
from .state import State

logger = logging.getLogger(__name__)


async def _serve(manifest: Path | None = None, *, interval: float = 0.5) -> int:
    manifest = manifest if manifest is not None else paths.manifest_path()
    if not manifest.is_file():
        return 0
    directory = paths.data_dir()
    settings = SettingsReader(paths.shell_json_path())
    embedder = Adapter(Embedder(binary=paths.runtime_bin(), model_dir=paths.model_dir()))
    server = IpcServer(paths.socket_path())
    service = SearchService(directory / "index", settings.read, embedder, server.state)
    server.service = service
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    signals = (signal.SIGINT, signal.SIGTERM)
    for signum in signals:
        loop.add_signal_handler(signum, stop.set)
    try:
        await server.start()
        while manifest.is_file() and not stop.is_set():
            await service.yield_to_indexer()
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
        await service.stop()
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
