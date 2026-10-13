import stat
from pathlib import Path


def check(data: Path, runtime: Path | None) -> list[dict]:
    problems = []

    def mode_of(path):
        try:
            return path.lstat().st_mode
        except OSError:
            return 0

    def entries(path):
        try:
            return sorted(path.iterdir())
        except OSError:
            return []

    def inspect(path, expected):
        mode = mode_of(path)
        if not mode:
            return False
        actual = stat.S_IMODE(mode)
        if actual != expected:
            problems.append({'path': str(path), 'expected': f'{expected:04o}',
                             'actual': f'{actual:04o}'})
        return stat.S_ISDIR(mode)

    if inspect(data, 0o700):
        for child in entries(data):
            mode = mode_of(child)
            if stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
                inspect(child, 0o700)
        for name in ('index', 'thumbs', 'model'):
            directory = data / name
            mode = mode_of(directory)
            if not stat.S_ISDIR(mode):
                continue
            for child in entries(directory):
                if name == 'index':
                    inspect(child, 0o600)
                elif name == 'model' and child.name.endswith(('.gguf', '.gguf.part')):
                    inspect(child, 0o600)
                elif name == 'thumbs' and inspect(child, 0o700):
                    for image in entries(child):
                        if image.name.endswith('.jpg'):
                            inspect(image, 0o600)
        for name in ('journal', 'running', 'index.lock', 'index.want'):
            inspect(data / name, 0o600)
    if runtime is not None and inspect(runtime, 0o700):
        inspect(runtime / 'ui.sock', 0o600)
        inspect(runtime / 'preview', 0o700)
    return problems


def fix_dirs(data: Path) -> None:
    if not stat.S_ISDIR(data.lstat().st_mode):
        return
    data.chmod(0o700)
    for child in data.iterdir():
        if stat.S_ISDIR(child.lstat().st_mode):
            child.chmod(0o700)
