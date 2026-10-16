import asyncio
import os

from . import errors

NEED_BYTES = 2_000_000_000


class DiskGuard:
    def __init__(self, path, *, statvfs=os.statvfs):
        self.path, self.statvfs = path, statvfs
        self.paused = False

    def free_bytes(self) -> int:
        stat = self.statvfs(self.path)
        return stat.f_bavail * stat.f_frsize

    def low(self) -> bool:
        return self.free_bytes() < NEED_BYTES

    def check(self) -> dict | None:
        free = self.free_bytes()
        low = free < NEED_BYTES
        if low == self.paused:
            return None
        self.paused = low
        if low:
            return {'t': 'paused', 'error': errors.disk_low().to_dict(),
                    'free_gb': round(free / 1e9, 1), 'need_gb': 2}
        return {'t': 'resumed'}


async def wait_for_space(guard, *, sleep=asyncio.sleep, every=30) -> None:
    while guard.low():
        await sleep(every)
