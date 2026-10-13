from datetime import date, timedelta
from pathlib import Path

from omafindd.leftout import Listed


def documents_files() -> list[Listed]:
    files = []
    groups = [
        ('notes', 'md', 412), ('notes', 'png', 3),
        ('work/clients', 'md', 160), ('work/clients', 'pdf', 7), ('work/clients', 'png', 2),
        ('work/talks', 'md', 41), ('work/talks', 'pdf', 2), ('work/talks', 'jpg', 2),
        ('tax/2023', 'md', 10), ('tax/2023', 'pdf', 18), ('tax/2023', 'png', 6),
        ('tax/2024', 'md', 14), ('tax/2024', 'pdf', 22), ('tax/2024', 'png', 9),
        ('archive/2021-letters', 'txt', 18), ('archive/old-backups', 'zip', 31),
        ('archive/old-backups', 'tar.gz', 6), ('vault/daily', 'md', 90),
        ('vault/daily', 'png', 2), ('manuals', 'pdf', 18), ('manuals', 'png', 2),
    ]
    from omafindd.rules import classify

    for folder, ext, count in groups:
        for n in range(count):
            parent = f'{folder}/part-{n % 3}' if folder == 'notes' else folder
            path = f'{parent}/reading-note-{n}.{ext}'
            files.append(Listed(path, classify(Path(path)), False))
    for n in range(58):
        day = date(2024, 1, 1) + timedelta(days=n)
        files.append(Listed(f'vault/exports/inv-{day:%Y%m%d}.txt', 'text', False))
    for path in ('tax/2024/.env.md', 'work/clients/.env.txt', 'work/clients/.env.local.md'):
        files.append(Listed(path, 'text', True))
    files.append(Listed('tax/2024/passwords.kdbx', None, True))
    return files


def make_documents(root: Path):
    for file in documents_files():
        path = root / file.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
