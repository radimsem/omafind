import asyncio
import json
import logging
import os
import socket
import stat
import struct
from pathlib import Path

from .state import State

PROTOCOL_VERSION = 1
MAX_LINE = 1_048_576
logger = logging.getLogger(__name__)


def peer_uid(sock) -> int:
    credentials = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    return struct.unpack("3i", credentials)[1]


class AlreadyRunning(Exception):
    pass


class IpcServer:
    def __init__(self, path: Path, state: State | None = None, *, peer_uid=peer_uid,
                 service=None) -> None:
        self.path = path
        self.service = service
        self._results = {}
        self.state = state if state is not None else State.detect()
        self.state.on_change = self.broadcast
        self.peer_uid = peer_uid
        self._server: asyncio.Server | None = None
        self._clients: set[asyncio.StreamWriter] = set()
        self._ready: set[asyncio.StreamWriter] = set()
        self._tasks: set[asyncio.Task] = set()

    async def start(self) -> None:
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.path.parent.chmod(0o700)
        if self.path.exists() or self.path.is_symlink():
            if not stat.S_ISSOCK(self.path.lstat().st_mode):
                raise FileExistsError(f"The socket path is occupied by a non-socket: {self.path}")
            try:
                _, writer = await asyncio.open_unix_connection(self.path)
            except ConnectionRefusedError:
                self.path.unlink()
            else:
                writer.close()
                await writer.wait_closed()
                raise AlreadyRunning(f"A helper already listens on {self.path}.")
        old_umask = os.umask(0o177)
        try:
            self._server = await asyncio.start_unix_server(
                # The stream limit includes the newline after a MAX_LINE-byte payload.
                self._accept, path=self.path, limit=MAX_LINE + 1,
            )
        finally:
            os.umask(old_umask)
        self.path.chmod(0o600)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
        # Since Python 3.12, wait_closed also waits for open connections.
        for writer in tuple(self._clients):
            writer.close()
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._server is not None:
            await self._server.wait_closed()
            self._server = None
            self.path.unlink(missing_ok=True)

    def _accept(self, reader, writer) -> None:
        self._clients.add(writer)
        task = asyncio.create_task(self._client(reader, writer))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _client(self, reader, writer) -> None:
        requests = set()
        try:
            if self.peer_uid(writer.get_extra_info("socket")) != os.getuid():
                return
            while True:
                try:
                    line = await reader.readline()
                except ValueError:
                    return
                if not line or len(line.removesuffix(b"\n")) > MAX_LINE:
                    return
                if not line.endswith(b"\n"):
                    return
                try:
                    message = json.loads(line)
                except (ValueError, UnicodeError):
                    logger.warning("Ignoring an invalid JSON object on the UI socket.")
                    continue
                if not isinstance(message, dict):
                    logger.warning("Ignoring a non-object on the UI socket.")
                    continue
                version = message.get("v")
                if "v" in message and (type(version) is not int or version != PROTOCOL_VERSION):
                    return
                if message.get("t") == "hello":
                    if type(version) is not int or version != PROTOCOL_VERSION:
                        return
                    await self._send(writer, self.state.message())
                    self._ready.add(writer)
                elif message.get("t") in ("search", "warm") and writer in self._ready:
                    task = asyncio.create_task(self.dispatch(writer, message))
                    requests.add(task)
                    self._tasks.add(task)
                    task.add_done_callback(requests.discard)
                    task.add_done_callback(self._tasks.discard)
                else:
                    logger.debug("Ignoring an unknown UI socket message type.")
        except (ConnectionError, OSError):
            pass
        finally:
            for task in requests:
                task.cancel()
            await asyncio.gather(*requests, return_exceptions=True)
            self._clients.discard(writer)
            self._ready.discard(writer)
            self._results.pop(writer, None)
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def dispatch(self, writer, message: dict) -> None:
        if self.service is None:
            return
        try:
            reply = await self.service.handle(message)
        except Exception as error:
            reply = {"t": "error", "seq": message.get("seq"), "reason": str(error)}
        if reply["t"] == "results":
            self._results[writer] = {item["id"]: item for item in reply["items"]}
        try:
            await self._send(writer, reply)
        except (ConnectionError, OSError):
            writer.close()

    def resolve(self, writer, item_id):
        return self._results.get(writer, {}).get(item_id)

    async def _send(self, writer, message: dict) -> None:
        line = json.dumps(message, separators=(",", ":"), ensure_ascii=False) + "\n"
        writer.write(line.encode())
        await writer.drain()

    async def broadcast(self, message: dict) -> None:
        for writer in tuple(self._ready):
            try:
                await self._send(writer, message)
            except (ConnectionError, OSError):
                writer.close()
