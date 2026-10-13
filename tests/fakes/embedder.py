import hashlib
import re
from collections.abc import Sequence

import numpy as np
from omafindd.embedder import InputAudio, Mode, Part, Text
from omafindd.extractors import ImagePart


class FakeEmbedder:
    def __init__(self):
        self.mode: Mode | None = None

    async def start(self, mode: Mode) -> None:
        self.mode = mode

    async def stop(self) -> None:
        self.mode = None

    def _vector(self, text: str) -> np.ndarray:
        vector = np.zeros(768, dtype=np.float32)
        words = re.findall(r"[^\W_]+", text.lower()) or ["empty"]
        for word in words:
            digest = hashlib.sha256(word.encode()).digest()
            vector[int.from_bytes(digest[:4]) % 768] += 1
        return (vector / np.linalg.norm(vector)).astype(np.float16)

    async def embed_query(self, text: str) -> np.ndarray:
        return self._vector(text)

    async def embed_documents(self, parts: list[str | ImagePart | InputAudio]) -> list[np.ndarray]:
        return [self._vector(part.split(" | text: ", 1)[-1]) if isinstance(part, str)
                else self._vector(hashlib.sha256(
                    part.data.encode() if isinstance(part, InputAudio) else part.data
                ).hexdigest()) for part in parts]

    async def embed(self, parts: Sequence[Part]) -> list[np.ndarray]:
        return [self._vector(part.text.split(" | query: ", 1)[-1].split(" | text: ", 1)[-1])
                if isinstance(part, Text) else self._vector(hashlib.sha256(repr(part).encode())
                                                          .hexdigest()) for part in parts]
