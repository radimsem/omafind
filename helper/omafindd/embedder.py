import asyncio
import os
import secrets
import socket
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx
import numpy as np

from omafindd.models import FILES

Mode = Literal["text", "full"]
Device = Literal["gpu", "cpu"]


class EmbeddingError(Exception):
    pass


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


class Embedder:
    def __init__(self, *, binary=None, model_dir=None, runner=subprocess.run,
                 spawner=asyncio.create_subprocess_exec, startup_timeout=60.0,
                 stop_timeout=5.0):
        self.binary = binary
        self.model_dir = model_dir
        self.runner = runner
        self.spawner = spawner
        self.startup_timeout = startup_timeout
        self.stop_timeout = stop_timeout
        self.mode: Mode | None = None
        self._process = None
        self._client = None
        self._lock = asyncio.Lock()

    async def start(self, mode: Mode) -> None:
        async with self._lock:
            if self.mode == mode and self._process is not None and self._process.returncode is None:
                return
            await self._stop()
            binary, directory = self.binary, self.model_dir
            if binary is None or directory is None:
                from omafindd import paths

                binary = paths.runtime_bin() if binary is None else binary
                directory = paths.model_dir() if directory is None else directory
            free_mib = await asyncio.to_thread(free_vram, self.runner)
            device = choose_device(mode, free_mib)
            devices = [device, "cpu"] if free_mib is None else [device]
            for attempt, device in enumerate(devices):
                try:
                    with socket.socket() as sock:
                        sock.bind(("127.0.0.1", 0))
                        port = sock.getsockname()[1]
                    api_key = secrets.token_urlsafe(32)
                    self._process = await self.spawner(
                        *build_command(binary, directory, mode, device, port),
                        env={**os.environ, "LLAMA_API_KEY": api_key},
                        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                    )
                    self._client = httpx.AsyncClient(
                        base_url=f"http://127.0.0.1:{port}",
                        headers={"Authorization": f"Bearer {api_key}"},
                        trust_env=False, timeout=30,
                    )
                    await self._wait_ready(self._process, self._client)
                except (OSError, EmbeddingError) as error:
                    await self._stop()
                    if attempt == len(devices) - 1:
                        raise EmbeddingError("Embedding server failed to start") from error
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
            raise EmbeddingError("Embedding server start timed out") from error
        raise EmbeddingError("Embedding server exited during start")

    async def stop(self) -> None:
        async with self._lock:
            await self._stop()

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
        async with self._lock:
            process, client = self._process, self._client
            if (self.mode is None or process is None or client is None
                    or process.returncode is not None):
                raise EmbeddingError("Embedding server is not running")
            vectors = []
            for offset in range(0, len(parts), 16):
                if process.returncode is not None:
                    raise EmbeddingError("Embedding server is not running")
                batch = parts[offset:offset + 16]
                try:
                    response = await client.post("/v1/embeddings", json=build_request(batch))
                    response.raise_for_status()
                except (httpx.HTTPError, RuntimeError) as error:
                    raise EmbeddingError("Embedding request failed") from error
                if process.returncode is not None:
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
