import base64
from typing import Protocol

import numpy as np

from .embedder import Embedder as RuntimeEmbedder
from .embedder import ImageUrl, InputAudio, Text, query_text
from .extractors import ImagePart


class Embedder(Protocol):
    async def start(self, mode: str) -> None: ...
    async def stop(self) -> None: ...
    async def embed_query(self, text: str) -> np.ndarray: ...
    async def embed_documents(
        self, parts: list[str | ImagePart | InputAudio]
    ) -> list[np.ndarray]: ...


class Adapter:
    def __init__(self, runtime: RuntimeEmbedder):
        self.runtime = runtime

    @property
    def mode(self):
        return self.runtime.mode

    @property
    def shared(self):
        return self.runtime.shared

    @property
    def connection_env(self):
        return self.runtime.connection_env

    async def start(self, mode):
        await self.runtime.start(mode)

    async def stop(self):
        await self.runtime.stop()

    async def embed_query(self, text: str) -> np.ndarray:
        return (await self.runtime.embed([Text(query_text(text))]))[0]

    async def embed_documents(self, parts: list[str | ImagePart | InputAudio]) -> list[np.ndarray]:
        inputs = [
            Text(part)
            if isinstance(part, str)
            else part
            if isinstance(part, InputAudio)
            else ImageUrl("data:image/png;base64," + base64.b64encode(part.data).decode())
            for part in parts
        ]
        vectors = []
        for offset in range(0, len(inputs), 16):
            vectors.extend(await self.runtime.embed(inputs[offset : offset + 16]))
        return vectors


def validated(vector) -> np.ndarray:
    try:
        value = np.asarray(vector, dtype=np.float32)
        if value.shape != (768,) or not np.isfinite(value).all():
            raise ValueError("embedding precision fault")
        norm = float(np.linalg.norm(value))
        if abs(norm - 1) > 0.001:
            raise ValueError("embedding precision fault")
        return (value / norm).astype(np.float16)
    except (TypeError, ValueError) as error:
        raise ValueError("embedding precision fault") from error
