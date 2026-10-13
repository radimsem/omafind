import hashlib
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO = "ggml-org/embeddinggemma-2-GGUF"
REVISION = "bfcd298762cc34d0357ece5ebdd31791a3a374d8"
BASE_URL = f"https://huggingface.co/{REPO}/resolve/{REVISION}"


@dataclass(frozen=True)
class ModelFile:
    name: str
    size: int
    sha256: str


FILES = (
    ModelFile("embeddinggemma-2-Q8_0.gguf", 309855456,
              "2188ac1deca4b77dffefd603c2776a9d76d9d74ec01841392982ebb840b09135"),
    ModelFile("mmproj-embeddinggemma-2-Q8_0.gguf", 554821024,
              "c4a8a52691ecef40618438928bdf9e68379b854e24166f292592353db0aab64f"),
)


def _directory(dest_dir: Path | str | None) -> Path:
    if dest_dir is None:
        from omafindd import paths

        return paths.model_dir()
    return Path(dest_dir)


def _valid(path: Path, file: ModelFile) -> bool:
    try:
        if not path.is_file() or path.stat().st_size != file.size:
            return False
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest() == file.sha256
    except OSError:
        return False


def verify(dest_dir: Path | str | None = None, *, files: Sequence[ModelFile] = FILES
           ) -> dict[str, bool]:
    directory = _directory(dest_dir)
    return {file.name: _valid(directory / file.name, file) for file in files}


class Verifier:
    def __init__(self, directory=None, files=FILES):
        self.directory = _directory(directory)
        self.files = tuple(files)
        self._signatures = {}
        self._report = {}

    def check(self) -> bool:
        for file in self.files:
            path = self.directory / file.name
            try:
                info = path.stat()
                signature = (info.st_size, info.st_mtime_ns, info.st_ino)
            except OSError:
                signature = None
            if file.name not in self._report or self._signatures[file.name] != signature:
                ok = signature is not None and _valid(path, file)
                self._signatures[file.name] = signature
                self._report[file.name] = {
                    'size': signature[0] if signature else None,
                    'mtime_ns': signature[1] if signature else None, 'ok': ok}
        return all(item['ok'] for item in self._report.values())

    def files_report(self) -> dict:
        return {name: dict(item) for name, item in self._report.items()}


def download(dest_dir: Path | str | None = None, files: Sequence[ModelFile] = FILES,
             base_url: str = BASE_URL,
             progress: Callable[[str, int, int], None] | None = None) -> None:
    import httpx

    for file in files:
        if "F16" in file.name:
            raise ValueError("F16 models are unsupported")
    if dest_dir is None:
        from omafindd import paths

        paths.data_dir()
    directory = _directory(dest_dir)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with httpx.Client(follow_redirects=True) as client:
        for file in files:
            final = directory / file.name
            if _valid(final, file):
                final.chmod(0o600)
                continue
            part = directory / f"{file.name}.part"
            offset = part.stat().st_size if part.exists() else 0
            if offset > file.size:
                part.unlink()
                raise ValueError(f"Model size mismatch: {file.name}")
            if offset < file.size:
                headers = {"Range": f"bytes={offset}-"} if offset else {}
                with client.stream("GET", f"{base_url.rstrip('/')}/{file.name}",
                                   headers=headers) as response:
                    response.raise_for_status()
                    if response.status_code == 206:
                        if not response.headers.get("Content-Range", "").startswith(
                            f"bytes {offset}-"
                        ):
                            part.unlink(missing_ok=True)
                            raise ValueError(f"Model size mismatch: {file.name}")
                    else:
                        offset = 0
                    flags = os.O_WRONLY | os.O_CREAT | (os.O_APPEND if offset else os.O_TRUNC)
                    with os.fdopen(os.open(part, flags, 0o600), "wb") as stream:
                        part.chmod(0o600)
                        for chunk in response.iter_bytes(1024 * 1024):
                            stream.write(chunk)
                            offset += len(chunk)
                            if progress is not None:
                                progress(file.name, offset, file.size)
            if part.stat().st_size != file.size:
                part.unlink()
                raise ValueError(f"Model size mismatch: {file.name}")
            if not _valid(part, file):
                part.unlink()
                raise ValueError(f"Model sha256 mismatch: {file.name}")
            part.chmod(0o600)
            part.replace(final)
