import asyncio
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parents[1] / 'fixtures/volumes'


def test_parse_poll_pairs_fixture():
    from omafindd.volumes import parse_poll

    events = [parse_poll(line) for line in (FIXTURES / 'poll-pairs.txt').read_text().splitlines()]
    assert [event.action for event in events] == ['mount', 'umount']
    assert events[0].uuid == '6BFF-B220'
    assert events[0].target == Path('/run/media/radimsem/Photos2024')
    event = parse_poll(r'ACTION="move" TARGET="/media/My\x20drive" '
                       'SOURCE="/dev/sdb1" FSTYPE="ext4" UUID="abc"')
    assert event.target == Path('/media/My drive')
    assert parse_poll('garbage') is None and parse_poll('') is None


def test_parse_lsblk_loop_is_removable():
    from omafindd.volumes import parse_lsblk

    facts = parse_lsblk(json.loads((FIXTURES / 'lsblk-loop.json').read_text()))
    drive = facts['6BFF-B220']
    assert drive.removable and drive.online
    assert (drive.label, drive.fs, drive.size) == ('Photos2024', 'exfat', 268435456)


def test_appear_unknown_then_known_return_then_gone():
    from omafindd.volumes import Volumes, parse_poll

    known, ignored = set(), set()
    data = json.loads((FIXTURES / 'lsblk-loop.json').read_text())
    volumes = Volumes(lsblk=lambda: data, known=known.__contains__, ignored=lambda: ignored)
    volumes.snapshot()
    lines = (FIXTURES / 'poll-pairs.txt').read_text().splitlines()
    mount, unmount = [parse_poll(line) for line in lines]
    assert volumes.step(mount)[0].kind == 'appeared'
    assert volumes.step(mount) == []
    known.add('6BFF-B220')
    assert volumes.step(unmount)[0].kind == 'gone'
    assert not volumes.last('6BFF-B220').online
    assert volumes.step(mount)[0].kind == 'returned'
    volumes.step(unmount)
    known.clear()
    ignored.add('6BFF-B220')
    assert volumes.step(mount) == []
    assert '6BFF-B220' in volumes.online()


def test_drive_at_new_mount_remaps_old_db_roots(tmp_path):
    from omafindd.volumes import remap_root

    old, new = tmp_path / 'old', tmp_path / 'new'
    root = {'path': str(old / 'Photos'), 'volume': 'v',
            'excludes': [str(old / 'Photos/private'), 'other']}
    mapped = remap_root(root, {'v': new}, {'v': old})
    assert mapped == {'path': str(new / 'Photos'), 'volume': 'v',
                      'excludes': [str(new / 'Photos/private'), 'other']}
    assert remap_root(root, {}, {'v': old}) is None
    assert root['path'] == str(old / 'Photos')


async def test_dead_findmnt_restarts_with_backoff():
    from omafindd.volumes import POLL_ARGV, Volumes

    class Dead:
        def __init__(self):
            self.stdout = asyncio.StreamReader()
            self.stdout.feed_eof()
            self.returncode = 1

        async def wait(self):
            return self.returncode

    starts, delays = [], []

    async def spawn(*args, **kwargs):
        starts.append(args)
        return Dead()

    async def sleep(delay):
        delays.append(delay)
        if len(delays) == 8:
            raise asyncio.CancelledError()

    async def events(items):
        raise AssertionError('dead child has no events')

    volumes = Volumes(lsblk=lambda: {}, known=lambda uuid: False, ignored=set)
    with pytest.raises(asyncio.CancelledError):
        await volumes.run(events, spawn=spawn, sleep=sleep)
    assert starts == [tuple(POLL_ARGV)] * 8
    assert delays == [0.5, 1, 2, 4, 8, 16, 30, 30]


def test_pseudo_and_system_mounts_are_not_drives():
    from omafindd.volumes import is_drive, parse_poll

    for target, fs in [('/', 'btrfs'), ('/home', 'btrfs'), ('/mnt/x', 'tmpfs')]:
        event = parse_poll(f'ACTION="mount" TARGET="{target}" SOURCE="dev" FSTYPE="{fs}" UUID="v"')
        assert not is_drive(event)


def test_lsblk_failure_does_not_end_step(caplog):
    import subprocess

    from omafindd.volumes import Volumes, parse_poll

    def broken():
        raise subprocess.CalledProcessError(1, ['private/path'], output='private text')

    volumes = Volumes(lsblk=broken, known=lambda uuid: True, ignored=set)
    event = parse_poll('ACTION="mount" TARGET="/media/fixture" FSTYPE="exfat" UUID="v"')
    assert volumes.step(event) == []
    assert 'private/path' not in caplog.text and 'private text' not in caplog.text


async def test_mount_tracking_retries_lsblk_and_callback_without_new_event():
    import sqlite3
    import subprocess

    from omafindd.volumes import Volumes

    reads, delivered = [], []

    def facts():
        reads.append(1)
        if len(reads) == 1:
            raise subprocess.CalledProcessError(1, ['lsblk'])
        return {'blockdevices': [{'uuid': 'v', 'fstype': 'exfat',
                                  'mountpoints': ['/media/fixture']}]}

    class Process:
        returncode = None

        def __init__(self):
            self.stdout = asyncio.StreamReader()
            self.stdout.feed_data(
                b'ACTION="mount" TARGET="/media/fixture" FSTYPE="exfat" UUID="v"\n')
            self.stdout.feed_eof()

        def terminate(self):
            self.returncode = 1

        async def wait(self):
            self.returncode = 1
            return 1

    async def spawn(*args, **kwargs):
        return Process()

    async def events(items):
        delivered.append(items)
        if len(delivered) == 1:
            raise sqlite3.OperationalError('injected I/O failure')
        raise asyncio.CancelledError()

    async def sleep(delay):
        pass

    volumes = Volumes(lsblk=facts, known=lambda uuid: True, ignored=set)
    with pytest.raises(asyncio.CancelledError):
        await volumes.run(events, spawn=spawn, sleep=sleep)
    assert len(reads) == 2
    assert delivered[0] == delivered[1]
    assert delivered[1][0].kind == 'returned'
