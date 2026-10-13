import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from . import paths
from .models import Verifier


@dataclass
class State:
    runtime: str = "missing"
    model: str = "missing"
    embedder: str = "stopped"
    # Fingerprint of the plugin code this daemon started from; set once at start.
    build: str = ""
    on_change: Callable[[dict], Awaitable[None]] | None = field(
        default=None, repr=False, compare=False,
    )

    @classmethod
    def detect(cls, verifier=None):
        binary = paths.runtime_bin()
        models = paths.model_dir()
        verifier = verifier if verifier is not None else Verifier(models)
        return cls(
            runtime="ready" if binary.is_file() and os.access(binary, os.X_OK) else "missing",
            model="ready" if all((models / name).is_file() for name in (
                "embeddinggemma-2-Q8_0.gguf", "mmproj-embeddinggemma-2-Q8_0.gguf",
            )) and verifier.check() else "missing",
        )

    def message(self) -> dict:
        return {"t": "state", "v": 1, "runtime": self.runtime,
                "model": self.model, "embedder": self.embedder, "build": self.build}

    async def update(self, **fields) -> None:
        changed = False
        for name, value in fields.items():
            if name not in ("runtime", "model", "embedder"):
                raise ValueError(f"Unknown state field: {name}")
            if getattr(self, name) != value:
                setattr(self, name, value)
                changed = True
        if changed and self.on_change is not None:
            await self.on_change(self.message())
