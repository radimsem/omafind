import asyncio
import contextlib
import ctypes
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Literal

import httpx
import numpy as np

from omafindd import errors
from omafindd.models import FILES

Mode = Literal["text", "full"]
Device = Literal["gpu", "cpu"]


def loopback_url(url):
    """Return url when it names a llama-server on this host's loopback, else None."""
    if not url:
        return None
    try:
        parsed = httpx.URL(url)
        port = parsed.port
    except (httpx.InvalidURL, ValueError):
        return None
    if parsed.scheme != "http" or parsed.host != "127.0.0.1" or port is None:
        return None
    if parsed.path not in ("", "/") or parsed.query or parsed.userinfo:
        return None
    return url


class EmbeddingError(Exception):
    user_error = None

    def __init__(self, *args, user_error=None):
        super().__init__(*args)
        self.user_error = user_error


class EmbeddingRejected(EmbeddingError):
    """The server answered with an error status; the input, not the server, is at fault."""


@dataclass(frozen=True)
class Text:
    text: str


@dataclass(frozen=True)
class ImageUrl:
    url: str


@dataclass(frozen=True)
class InputAudio:
    data: str
    format: Literal["wav"] = "wav"


Part = Text | ImageUrl | InputAudio


def choose_device(mode: Mode, free_mib: int | None) -> Literal["gpu", "cpu"]:
    return "gpu" if free_mib is None or free_mib >= (1536 if mode == "full" else 512) else "cpu"


def free_vram(runner=subprocess.run) -> int | None:
    try:
        result = runner(["nvidia-smi", "--query-gpu=memory.free",
                         "--format=csv,noheader,nounits"],
                        capture_output=True, text=True, check=True, timeout=5)
        if result.returncode != 0:
            return None
        return int(result.stdout.strip())
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def server_argv(binary, model, mmproj, port: int, device: Device) -> list[str]:
    argv = [str(binary), "-m", str(model)]
    if mmproj is not None:
        argv.extend(["--mmproj", str(mmproj)])
    tokens = "2048" if mmproj is not None else "512"
    # Non-causal embeddings must fit a whole input in one micro-batch.
    argv.extend(["--embeddings", "--pooling", "mean", "--host", "127.0.0.1",
                 "--port", str(port), "--ctx-size", tokens,
                 "--batch-size", tokens, "--ubatch-size", tokens,
                 "--parallel", "16", "--kv-unified"])
    if mmproj is not None:
        # The default minimum of 70 tokens would upscale a pre-resized 63-token image again.
        argv.extend(["--image-min-tokens", "1"])
    if device == "cpu" and mmproj is not None:
        argv.append("--no-mmproj-offload")
    argv.extend(["-ngl", "99" if device == "gpu" else "0"])
    return ["nice", "-n", "19", *argv] if device == "cpu" else argv


def build_command(binary, model_dir, mode: Mode, device: Device, port: int) -> list[str]:
    directory = Path(model_dir)
    return server_argv(binary, directory / FILES[0].name,
                       directory / FILES[1].name if mode == "full" else None,
                       port, device)


def build_request(parts: Sequence[Part]) -> dict:
    inputs = []
    for part in parts:
        if isinstance(part, Text):
            content = {"type": "text", "text": part.text}
        elif isinstance(part, ImageUrl):
            content = {"type": "image_url", "image_url": {"url": part.url}}
        elif isinstance(part, InputAudio):
            content = {"type": "input_audio", "input_audio": {
                "data": part.data, "format": part.format,
            }}
        else:
            raise TypeError("Unsupported embedding part")
        inputs.append({"content": [content]})
    return {"input": inputs, "encoding_format": "float"}


def query_text(q: str) -> str:
    return f"task: search result | query: {q}"


def document_text(title: str, chunk: str) -> str:
    return f"title: {title} | text: {chunk}"


def _parent_death_signal(parent, sig=signal.SIGTERM):
    if ctypes.CDLL(None, use_errno=True).prctl(1, sig, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "Could not set parent death signal")
    if os.getppid() != parent:
        os.kill(os.getpid(), sig)


REQUEST_SLOTS = 2
SERVER_LOG = "llama-server.log"
_LOG_CAUSE = re.compile(r"error|failed|no devices", re.IGNORECASE)


def _open_log():
    from omafindd import paths

    try:
        path = paths.logs_dir() / SERVER_LOG
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.fchmod(fd, 0o600)
            return path, os.fdopen(fd, "wb")
        except OSError:
            os.close(fd)
            raise
    except OSError:
        return None, None


def _log_cause(path) -> str | None:
    """The last line of a server log that names an error, cut to 100 characters."""
    if path is None:
        return None
    try:
        tail = Path(path).read_bytes()[-65536:].decode(errors="replace")
    except OSError:
        return None
    line = next((line.strip() for line in reversed(tail.splitlines())
                 if _LOG_CAUSE.search(line)), None)
    if not line:
        return None
    line = line.rstrip(".")
    return line if len(line) <= 100 else line[:99].rstrip() + "…"


def _attempt_cause(error, log_path) -> str:
    clause = (str(error) if isinstance(error, EmbeddingError)
              else f"It could not be started ({error.strerror or error})")
    line = _log_cause(log_path)
    return clause if line is None else f"{clause} ({line})"


def _start_cause(causes) -> str:
    if len(causes) == 1:
        return causes[0][1]
    return "; ".join(f"{device.upper()}: {cause[:1].lower()}{cause[1:]}"
                     for device, cause in causes)


class Embedder:
    def __init__(self, *, binary=None, model_dir=None, runner=subprocess.run,
                 spawner=asyncio.create_subprocess_exec, startup_timeout=60.0,
                 stop_timeout=5.0, base_url=None, api_key=None):
        self.binary = binary
        self.model_dir = model_dir
        self.runner = runner
        self.spawner = spawner
        self.startup_timeout = startup_timeout
        self.stop_timeout = stop_timeout
        self.shared = base_url is not None
        self._base_url, self._api_key = base_url, api_key
        self.mode: Mode | None = None
        self._process = None
        self._client = None
        self._lock = asyncio.Lock()
        self._requests = asyncio.Semaphore(REQUEST_SLOTS)

    def ready(self, mode: Mode) -> bool:
        if self._client is None or not (self.mode == mode or self.mode == "full"):
            return False
        return self.shared or self._process is not None and self._process.returncode is None

    @property
    def connection_env(self):
        if self.mode is None or self._client is None:
            return {}
        return {'OMAFIND_EMBED_URL': str(self._client.base_url).rstrip('/'),
                'OMAFIND_EMBED_KEY': self._api_key}

    async def start(self, mode: Mode) -> None:
        async with self._lock:
            if (self.mode == mode or self.mode == 'full' and mode == 'text') and (
                    self.shared or self._process is not None
                    and self._process.returncode is None):
                return
            async with self._drained():
                await self._stop()
            if self.shared:
                self._client = httpx.AsyncClient(
                    base_url=self._base_url,
                    headers={'Authorization': f'Bearer {self._api_key}'},
                    trust_env=False, timeout=30,
                )
                try:
                    response = await self._client.get('/health')
                    response.raise_for_status()
                except (httpx.HTTPError, RuntimeError) as error:
                    await self._stop()
                    raise EmbeddingError('Shared embedding server is not running') from error
                except BaseException:
                    await self._stop()
                    raise
                self.mode = 'full'
                return
            binary, directory = self.binary, self.model_dir
            if binary is None or directory is None:
                from omafindd import paths

                binary = paths.runtime_bin() if binary is None else binary
                directory = paths.model_dir() if directory is None else directory
            free_mib = await asyncio.to_thread(free_vram, self.runner)
            device = choose_device(mode, free_mib)
            devices = [device, "cpu"] if free_mib is None else [device]
            causes = []
            for attempt, device in enumerate(devices):
                log_path = None
                try:
                    with socket.socket() as sock:
                        sock.bind(("127.0.0.1", 0))
                        port = sock.getsockname()[1]
                    api_key = secrets.token_urlsafe(32)
                    self._api_key = api_key
                    # Truncated per attempt, so after a GPU then CPU failure it holds the CPU run.
                    log_path, log = _open_log()
                    try:
                        # The key goes only in the environment, never in argv.
                        self._process = await self.spawner(
                            *build_command(binary, directory, mode, device, port),
                            env={**os.environ, "LLAMA_API_KEY": api_key},
                            stdout=asyncio.subprocess.DEVNULL if log is None else log,
                            stderr=asyncio.subprocess.STDOUT,
                            preexec_fn=partial(_parent_death_signal, os.getpid())
                            if sys.platform == "linux" else None,
                        )
                    finally:
                        if log is not None:
                            log.close()
                    self._client = httpx.AsyncClient(
                        base_url=f"http://127.0.0.1:{port}",
                        headers={"Authorization": f"Bearer {api_key}"},
                        trust_env=False, timeout=30,
                    )
                    await self._wait_ready(self._process, self._client)
                except (OSError, EmbeddingError) as error:
                    await self._stop()
                    causes.append((device, _attempt_cause(error, log_path)))
                    if attempt == len(devices) - 1:
                        raise EmbeddingError(
                            "Embedding server failed to start",
                            user_error=errors.server_start_failed(_start_cause(causes), log_path),
                        ) from error
                except BaseException:
                    await self._stop()
                    raise
                else:
                    self.mode = mode
                    return

    async def _wait_ready(self, process, client) -> None:
        try:
            async with asyncio.timeout(self.startup_timeout):
                while process.returncode is None:
                    try:
                        response = await client.get("/health")
                        if response.status_code == 200:
                            return
                    except httpx.HTTPError:
                        pass
                    await asyncio.sleep(0.01)
        except TimeoutError as error:
            raise EmbeddingError(f"It did not answer within {self.startup_timeout:g} s") from error
        code = process.returncode
        raise EmbeddingError(f"It was stopped by signal {-code}" if code < 0
                             else f"It exited with code {code}")

    async def stop(self) -> None:
        async with self._lock, self._drained():
            await self._stop()

    @contextlib.asynccontextmanager
    async def _drained(self):
        # embed holds a request slot rather than the lock, so take every slot before a stop
        # kills the server or closes the client under an in-flight request.
        taken = 0
        try:
            while taken < REQUEST_SLOTS:
                await self._requests.acquire()
                taken += 1
            yield
        finally:
            for _ in range(taken):
                self._requests.release()

    async def _stop(self) -> None:
        process, client = self._process, self._client
        self._process = self._client = self.mode = None
        try:
            if process is not None and process.returncode is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(process.wait(), self.stop_timeout)
                except TimeoutError:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    await process.wait()
        finally:
            if client is not None:
                await client.aclose()

    async def embed(self, parts: Sequence[Part]) -> list[np.ndarray]:
        async with self._requests:
            process, client = self._process, self._client
            if (self.mode is None or client is None or not self.shared
                    and (process is None or process.returncode is not None)):
                raise EmbeddingError("Embedding server is not running")
            vectors = []
            for offset in range(0, len(parts), 16):
                if process is not None and process.returncode is not None:
                    raise EmbeddingError("Embedding server is not running")
                batch = parts[offset:offset + 16]
                try:
                    response = await client.post("/v1/embeddings", json=build_request(batch))
                    response.raise_for_status()
                except httpx.HTTPStatusError as error:
                    try:
                        message = str(error.response.json()["error"]["message"])
                    except (ValueError, KeyError, TypeError):
                        message = error.response.reason_phrase
                    status = error.response.status_code
                    # llama-server answers 500 when the input is over its batch size.
                    rejection = EmbeddingRejected if status in (400, 413, 500) else EmbeddingError
                    raise rejection(f"HTTP {status}: {message[:200]}") from error
                except (httpx.HTTPError, RuntimeError) as error:
                    raise EmbeddingError("Embedding request failed") from error
                if process is not None and process.returncode is not None:
                    raise EmbeddingError("Embedding server is not running")
                try:
                    rows = sorted(response.json()["data"], key=lambda row: row["index"])
                    if [row["index"] for row in rows] != list(range(len(batch))):
                        raise ValueError("Invalid embedding indexes")
                    embeddings = [row["embedding"] for row in rows]
                except (KeyError, TypeError, ValueError) as error:
                    raise EmbeddingError("Invalid embedding response") from error
                try:
                    for embedding in embeddings:
                        vector = np.asarray(embedding, dtype=np.float64)
                        if vector.shape != (768,) or not np.isfinite(vector).all():
                            raise ValueError("Invalid embedding vector")
                        norm = float(np.linalg.norm(vector))
                        if abs(norm - 1) > 1e-3:
                            raise ValueError("Invalid embedding norm")
                        vectors.append((vector / norm).astype(np.float16))
                except (TypeError, ValueError) as error:
                    raise EmbeddingError("embedding precision fault") from error
            return vectors
