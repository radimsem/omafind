from types import SimpleNamespace


def guard_at(free):
    from omafindd.diskguard import DiskGuard

    return DiskGuard('/data', statvfs=lambda path: SimpleNamespace(f_bavail=free, f_frsize=1))


def test_1_9_gb_pauses_with_need_gb_2():
    guard = guard_at(1_900_000_000)
    assert guard.low()
    assert guard.check() == {'t': 'paused', 'reason': 'disk', 'free_gb': 1.9, 'need_gb': 2}
    assert guard.check() is None


def test_2_1_gb_resumes():
    free = [1_900_000_000]
    from omafindd.diskguard import DiskGuard

    guard = DiskGuard('/data', statvfs=lambda path: SimpleNamespace(f_bavail=free[0], f_frsize=1))
    guard.check()
    free[0] = 2_100_000_000
    assert not guard.low() and guard.check() == {'t': 'resumed'}
    assert guard.check() is None


async def test_wait_for_space_blocks_until_available():
    from omafindd.diskguard import wait_for_space

    free, delays = [1_900_000_000], []
    from omafindd.diskguard import DiskGuard

    guard = DiskGuard('/data', statvfs=lambda path: SimpleNamespace(f_bavail=free[0], f_frsize=1))

    async def sleep(delay):
        delays.append(delay)
        free[0] = 2_000_000_000

    await wait_for_space(guard, sleep=sleep)
    assert delays == [30]
