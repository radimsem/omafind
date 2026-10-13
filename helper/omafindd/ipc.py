import asyncio
import json
import logging
import os
import socket
import sqlite3
import stat
import struct
import time
from contextlib import closing
from pathlib import Path
from threading import Lock

from . import opener
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
                 service=None, setup=None) -> None:
        self.path = path
        self.service = service
        self.setup = setup
        self.replay = lambda: []
        self._results = {}
        self._jumps = {}
        self._previews = {}
        self._status = None
        self._status_at = float("-inf")
        self._status_signature = None
        self._status_cached = None
        self._status_lock = Lock()
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
        task = asyncio.create_task(self._watch_status())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

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
        if self.setup is not None:
            await self.setup.stop()
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
                    for event in self.replay():
                        await self._send(writer, event)
                    self._ready.add(writer)
                elif (message.get("t") in ("search", "warm", "preview", "open", "status")
                      or (self.setup is not None and message.get("t") in self.setup.TYPES)) \
                        and writer in self._ready:
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
            self._jumps.pop(writer, None)
            self._previews.pop(writer, None)
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def dispatch(self, writer, message: dict) -> None:
        if self.setup is not None and message["t"] in self.setup.TYPES:
            try:
                reply = await self.setup.handle(message)
            except Exception as error:
                reply = {"t": "error", "for": message["t"], "reason": str(error)}
            try:
                await self._send(writer, reply)
            except (ConnectionError, OSError):
                writer.close()
            return
        if message["t"] == "preview":
            pending = self._previews.setdefault(writer, {"lock": asyncio.Lock()})
            token = pending["latest"] = object()
            async with pending["lock"]:
                if pending["latest"] is not token:
                    return
                try:
                    reply = await self._overlay(writer, message)
                except Exception as error:
                    reply = {"t": "error", "id": message.get("id"), "reason": str(error)}
                if pending["latest"] is not token:
                    return
                if reply["t"] == "preview":
                    self._jumps.setdefault(writer, {})[reply["id"]] = reply["jump"]
                try:
                    await self._send(writer, reply)
                except (ConnectionError, OSError):
                    writer.close()
            return
        try:
            if message["t"] == "status":
                reply = await asyncio.to_thread(self.status_message)
            elif message["t"] == "open":
                reply = await self._overlay(writer, message)
            elif self.service is not None:
                reply = await self.service.handle(message)
            else:
                return
        except Exception as error:
            reply = {"t": "error", "seq": message.get("seq"), "reason": str(error)}
            if message["t"] == "open":
                reply.update({"id": message.get("id"), "for": "open"})
        if reply["t"] == "results":
            self._results[writer] = {item["id"]: item for item in reply["items"]}
            self._jumps.pop(writer, None)
        try:
            await self._send(writer, reply)
        except (ConnectionError, OSError):
            writer.close()

    def resolve(self, writer, item_id):
        return self._results.get(writer, {}).get(item_id) if isinstance(item_id, str) else None

    async def _overlay(self, writer, message):
        item_id = message.get("id")
        item = self.resolve(writer, item_id)
        if message["t"] == "preview":
            from . import preview

            if item is None or (not item.get("offline") and not Path(item["path"]).is_file()):
                return {"t": "error", "id": item_id, "code": "missing", "reason": "File is missing"}
            query = message.get("q", "")
            if not isinstance(query, str):
                return {"t": "error", "id": item_id, "code": "bad-request",
                        "reason": "Invalid preview arguments"}
            rendering = asyncio.create_task(asyncio.to_thread(preview.render, item, query))
            try:
                reply = await asyncio.shield(rendering)
            except asyncio.CancelledError:
                # Cancelling to_thread does not stop its renderer; retain the connection slot.
                await asyncio.gather(rendering, return_exceptions=True)
                raise
            if self.resolve(writer, item_id) is not item:
                reply = {"t": "error", "id": item_id, "code": "missing",
                         "reason": "File is missing"}
            return reply
        if item is None:
            reason = "missing"
        elif item.get("offline"):
            reason = "offline"
        elif not Path(item["path"]).is_file():
            reason = "missing"
        else:
            reason = None
        if reason:
            return {"t": "open_failed", "id": item_id, "reason": reason}
        how = message.get("how", "open")
        if how not in ("open", "reveal"):
            return {"t": "error", "id": item_id, "for": "open", "code": "bad-request",
                    "reason": "Invalid open arguments"}
        target = dict(item)
        jump = self._jumps.get(writer, {}).get(item_id)
        if jump is not None:
            target["loc"] = jump
            if target["kind"] == "code":
                target["open_line"] = jump
        opener.launch(target, how=how)
        return {"t": "opened", "id": item_id, **opener.description(target, how=how)}

    def status_message(self):
        with self._status_lock:
            return self._read_status()

    def _read_status(self):
        files = done = total = 0
        failed = False
        roots = 0
        stores = []
        if self.service is not None and hasattr(self.service, "directory"):
            roots = len(self.service.settings().roots)
            stores = sorted(self.service.directory.glob("*.sqlite"))
        mounts = {}
        if self.service is not None:
            if hasattr(self.service, "current_mounts"):
                mounts = self.service.current_mounts()
            elif hasattr(self.service, "mounts_resolver"):
                mounts = self.service.mounts_resolver()
        signature = [tuple(sorted((uuid, str(mount)) for uuid, mount in mounts.items()))]
        offline = []
        for path in stores:
            for source in (path, Path(str(path) + "-wal")):
                try:
                    mtime = source.stat().st_mtime_ns
                except FileNotFoundError:
                    mtime = None
                signature.append((source, mtime))
        if signature == self._status_signature:
            return {**self._status_cached, "roots": roots}
        for path in stores:
            try:
                with closing(sqlite3.connect(path.absolute().as_uri() + "?mode=ro", uri=True,
                                             timeout=.05)) as db:
                    count, indexed, pending = db.execute(
                        "SELECT count(*),count(indexed_at),sum(state='pending' OR "
                        "(state='partial' AND detail IS NULL)) FROM files"
                    ).fetchone()
                    if path.name != "code.sqlite":
                        try:
                            meta = dict(db.execute("SELECT key,value FROM meta"))
                        except sqlite3.Error:
                            meta = {}
                        if meta.get("volume_uuid") and meta["volume_uuid"] not in mounts:
                            offline.append(meta.get("volume_label", path.stem))
            except sqlite3.Error:
                failed = True
                continue
            files += indexed
            total += count
            done += count - (pending or 0)
        # A store that failed to read is retried on the next tick.
        self._status_signature = None if failed else signature
        self._status_cached = {"t": "status", "files": files, "roots": roots, "offline": offline,
                               "done": done, "total": total}
        return self._status_cached

    async def push_status(self, *, now=None, force=False):
        message = await asyncio.to_thread(self.status_message)
        now = time.monotonic() if now is None else now
        if not force and (message == self._status or now - self._status_at < .5):
            return
        await self.broadcast(message)
        self._status, self._status_at = message, now

    async def _watch_status(self):
        while True:
            if self._ready:
                await self.push_status()
            if self.setup is not None:
                await self.setup.poll()
            await asyncio.sleep(.5)

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
