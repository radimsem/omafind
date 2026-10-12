import hashlib
from collections.abc import Sequence

import numpy as np
from omafindd.embedder import Mode, Part


class FakeEmbedder:
    def __init__(self):
        self.mode: Mode | None = None

    async def start(self, mode: Mode) -> None:
        self.mode = mode

    async def stop(self) -> None:
        self.mode = None

    async def embed(self, parts: Sequence[Part]) -> list[np.ndarray]:
        vectors = []
        for part in parts:
            digest = hashlib.sha256(repr(part).encode()).digest()
            vector = np.zeros(768, dtype=np.float16)
            vector[int.from_bytes(digest[:4]) % 768] = 1 if digest[4] & 1 else -1
            vectors.append(vector)
        return vectors
