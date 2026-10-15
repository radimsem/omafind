import asyncio
import os
from types import SimpleNamespace

import pytest
from omafindd import errors, models
from omafindd.install import RuntimeJob, gpu_name


class Process:
    def __init__(self, code=0, stderr=b"", waiting=False):
        self.pid = 12345
        self.returncode = None if waiting else code
        self.code = code
        self.stderr = asyncio.StreamReader()
        self.stderr.feed_data(stderr)
        self.stderr.feed_eof()
        self.finished = asyncio.Event()
        if not waiting:
            self.finished.set()

    async def wait(self):
        await self.finished.wait()
        self.returncode = self.code
        return self.code


@pytest.fixture(autouse=True)
async def wake_loop():
    # The sandbox blocks self-pipe sends, so thread completions need a timed loop wakeup.
    async def tick():
        while True:
            await asyncio.sleep(0.01)

    task = asyncio.create_task(tick())
    yield
    await asyncio.get_running_loop().shutdown_default_executor()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


@pytest.fixture
def job_factory(tmp_path, monkeypatch):
    monkeypatch.setattr("omafindd.install.shutil.which", lambda name: "/usr/bin/" + name)
    jobs = []

    def make(*, process=None, valid=None, download=None, clock=lambda: 10.0):
        messages, calls = [], []

        async def broadcast(message):
            messages.append(message)

        async def spawn(*args, **kw):
            calls.append((args, kw))
            return Process() if args[0] == "systemctl" else (process or Process())

        def fetch(directory, *, progress):
            for file in models.FILES:
                progress(file.name, file.size // 2, file.size)
                progress(file.name, file.size, file.size)

        job = RuntimeJob(
            data_dir=tmp_path,
            plugin_root=tmp_path / "plugin",
            broadcast=broadcast,
            spawn=spawn,
            download=download or fetch,
            valid=valid or (lambda directory: {f.name: True for f in models.FILES}),
            gpu=lambda: "RTX 3060 12 GB",
            clock=clock,
        )
        jobs.append(job)
        return job, messages, calls

    return make


async def finish(job):
    await job._task


async def test_build_runs_before_download_and_both_files_verify(job_factory):
    job, messages, calls = job_factory()
    assert (await job.start())["state"] == "running"
    await finish(job)
    result = job.snapshot()
    assert result["state"] == "done"
    assert result["done"] == result["total"] == 865
    assert result["files"]["model"]["done"] == 310
    assert result["files"]["mmproj"]["done"] == 555
    assert result["build"]["seconds"] == 0
    assert [m["build"]["state"] for m in messages][:3] == ["wait", "run", "ok"]
    assert any(m["files"]["model"]["state"] == "run" for m in messages)
    assert any(m["files"]["mmproj"]["state"] == "run" for m in messages)
    assert calls[-1][0] == (str(job.plugin_root / "scripts/build-runtime.sh"),)
    assert calls[-1][1]["start_new_session"] is True
    assert calls[-1][1]["env"]["OMAFIND_DATA_DIR"] == str(job.data_dir)


async def test_pause_during_build_kills_process_group_and_resume_reruns_script(
    job_factory, monkeypatch
):
    process = Process(waiting=True)
    job, messages, calls = job_factory(process=process)
    killed = []

    def kill(pid, signum):
        killed.append((pid, signum))
        process.code = -15
        process.finished.set()

    monkeypatch.setattr(os, "killpg", kill)
    await job.start()
    while job._process is None:
        await asyncio.sleep(0)
    assert (await job.pause())["state"] == "paused"
    assert killed[0][0] == process.pid
    process.code = 0
    await job.start()
    await finish(job)
    assert job.snapshot()["state"] == "done"
    assert len([c for c in calls if c[0][0].endswith("build-runtime.sh")]) == 2


async def test_pause_during_download_stops_at_next_chunk_and_resume_continues(job_factory):
    import threading

    chunk = threading.Event()
    release = threading.Event()
    calls = []

    def fetch(directory, *, progress):
        calls.append(directory)
        if len(calls) == 1:
            progress(models.FILES[0].name, 1, models.FILES[0].size)
            chunk.set()
            release.wait(2)
        progress(models.FILES[0].name, 2, models.FILES[0].size)

    job, _, _ = job_factory(download=fetch)
    await job.start()
    await asyncio.to_thread(chunk.wait, 2)
    pausing = asyncio.create_task(job.pause())
    await asyncio.sleep(0)
    release.set()
    assert (await pausing)["state"] == "paused"
    await job.start()
    await finish(job)
    assert len(calls) == 2
    assert job.snapshot()["state"] == "done"


async def test_build_failure_reports_last_stderr_line(job_factory):
    job, _, _ = job_factory(process=Process(1, b"first\nlast error\n"))
    assert job.snapshot()["error"] is None and "reason" not in job.snapshot()
    await job.start()
    await finish(job)
    assert job.snapshot()["build"]["state"] == "failed"
    assert job.snapshot()["error"] == errors.build_failed("last error").to_dict()


async def test_digest_mismatch_fails_with_model_verify_failed(job_factory):
    job, _, _ = job_factory(valid=lambda directory: {f.name: False for f in models.FILES})
    await job.start()
    await finish(job)
    assert job.snapshot()["state"] == "failed"
    assert job.snapshot()["error"] == errors.model_verify_failed(models.FILES[0].name).to_dict()


@pytest.mark.parametrize("raised,expected", [
    (OSError("connection refused"), errors.model_download_failed("connection refused")),
    (ValueError(f"Model sha256 mismatch: {models.FILES[1].name}"),
     errors.model_verify_failed(models.FILES[1].name)),
])
async def test_download_failure_names_its_cause(job_factory, raised, expected):
    def fetch(directory, *, progress):
        raise raised

    job, _, _ = job_factory(download=fetch)
    await job.start()
    await finish(job)
    assert job.snapshot()["state"] == "failed"
    assert job.snapshot()["build"]["state"] == "ok"
    assert job.snapshot()["error"] == expected.to_dict()


async def test_unexpected_failure_is_internal(job_factory):
    def broken(directory):
        raise RuntimeError("disk vanished")

    job, _, _ = job_factory(valid=broken)
    await job.start()
    await finish(job)
    assert job.snapshot()["error"] == errors.internal("disk vanished").to_dict()


async def test_restart_clears_the_error(job_factory):
    job, _, _ = job_factory(process=Process(1, b"boom\n"))
    await job.start()
    await finish(job)
    assert job.snapshot()["error"]["code"] == "build-failed"
    assert (await job.start())["error"] is None
    await finish(job)


async def test_existing_runtime_reports_installed_without_seconds(job_factory, tmp_path):
    binary = tmp_path / "runtime/bin/llama-server"
    binary.parent.mkdir(parents=True)
    binary.touch(mode=0o700)
    (tmp_path / "runtime/BUILD").touch()
    job, _, calls = job_factory()
    assert (await job.status())["state"] == "done"
    assert job.snapshot()["build"]["seconds"] is None
    assert not calls


async def test_status_verifies_once_until_file_metadata_changes(job_factory, tmp_path):
    calls = []
    job, _, _ = job_factory(valid=lambda directory: calls.append(directory) or {})
    await asyncio.gather(job.status(), job.status())
    assert len(calls) == 1
    (tmp_path / "model").mkdir()
    (tmp_path / "model" / models.FILES[0].name).touch()
    await job.status()
    assert len(calls) == 2


def test_gpu_name_parses_nvidia_smi():
    assert (
        gpu_name(
            lambda *a, **kw: SimpleNamespace(
                returncode=0, stdout="NVIDIA GeForce RTX 3060, 12288\n"
            )
        )
        == "RTX 3060 12 GB"
    )


def test_gpu_name_is_none_without_nvidia_smi():
    def missing(*args, **kw):
        raise FileNotFoundError

    assert gpu_name(missing) is None


async def test_runtime_progress_broadcast_at_most_twice_per_second(job_factory):
    times = iter([0.0, 0.1, 0.2, 0.6])

    def fetch(directory, *, progress):
        for done in (1, 2, 3, 4):
            progress(models.FILES[0].name, done, models.FILES[0].size)

    now = [0.0]
    job, messages, _ = job_factory(download=fetch, clock=lambda: now[0])
    original = job._progress

    def progress(*args):
        now[0] = next(times)
        original(*args)

    job._progress = progress
    await job.start()
    await finish(job)
    chunks = [m["done"] for m in messages if m["files"]["model"]["state"] == "run"]
    assert len(chunks) == 2


async def test_build_refuses_unavailable_memory_scope(job_factory, monkeypatch):
    job, _, calls = job_factory()
    monkeypatch.setattr("omafindd.install.shutil.which", lambda name: None)
    await job.start()
    await finish(job)
    assert job.snapshot()["state"] == "failed"
    assert job.snapshot()["error"] == errors.build_no_scope().to_dict()
    assert not calls


async def test_status_downgrades_done_when_a_verified_file_disappears(job_factory, tmp_path):
    binary = tmp_path / "runtime/bin/llama-server"
    binary.parent.mkdir(parents=True)
    binary.touch(mode=0o700)
    (tmp_path / "runtime/BUILD").touch()
    model = tmp_path / "model"
    model.mkdir()
    for file in models.FILES:
        (model / file.name).touch()
    job, _, _ = job_factory(
        valid=lambda directory: {f.name: (directory / f.name).exists() for f in models.FILES}
    )
    assert (await job.status())["state"] == "done"
    (model / models.FILES[0].name).unlink()
    assert (await job.status())["state"] == "idle"


async def test_disconnected_start_request_keeps_runtime_job(job_factory):
    job, _, _ = job_factory()
    original = job.broadcast
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocked(message):
        if message["state"] == "running" and message["step"] is None:
            entered.set()
            await release.wait()
        await original(message)

    job.broadcast = blocked
    request = asyncio.create_task(job.start())
    await entered.wait()
    if not request.done():
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
    else:
        assert (await request)["state"] == "running"
    release.set()
    assert job._task is not None
    await finish(job)
    assert job.snapshot()["state"] == "done"


async def test_runtime_left_seconds_uses_recent_bytes(job_factory):
    now = [0.0]

    def fetch(directory, *, progress):
        progress(models.FILES[0].name, 10_000_000, models.FILES[0].size)
        now[0] = 2.0
        progress(models.FILES[0].name, 30_000_000, models.FILES[0].size)

    job, messages, _ = job_factory(download=fetch, clock=lambda: now[0])
    await job.start()
    await finish(job)
    chunks = [m for m in messages if m["files"]["model"]["state"] == "run"]
    assert chunks[0]["left_seconds"] is None
    assert chunks[1]["left_seconds"] == 83


async def test_stop_pauses_without_broadcasting(job_factory, monkeypatch):
    process = Process(waiting=True)
    job, messages, _ = job_factory(process=process)
    monkeypatch.setattr(os, "killpg", lambda *args: process.finished.set())
    await job.start()
    while job._process is None:
        await asyncio.sleep(0)
    count = len(messages)
    await job.stop()
    assert len(messages) == count
    assert job.snapshot()["state"] == "paused"


async def test_paused_status_retains_download_progress(job_factory):
    import threading

    entered, release = threading.Event(), threading.Event()

    def fetch(directory, *, progress):
        progress(models.FILES[0].name, 20_000_000, models.FILES[0].size)
        entered.set()
        release.wait(2)
        progress(models.FILES[0].name, 21_000_000, models.FILES[0].size)

    job, _, _ = job_factory(download=fetch, valid=lambda _: {})
    await job.start()
    await asyncio.to_thread(entered.wait, 2)
    pausing = asyncio.create_task(job.pause())
    await asyncio.sleep(0)
    release.set()
    await pausing
    result = await job.status()
    assert result["state"] == "paused"
    assert result["done"] == 20
    assert result["files"]["model"]["state"] == "run"


async def test_build_elapsed_seconds_are_pushed_while_build_waits(job_factory, monkeypatch):
    process = Process(waiting=True)
    now = [0.0]
    job, messages, _ = job_factory(process=process, clock=lambda: now[0])
    monkeypatch.setattr(os, "killpg", lambda *args: process.finished.set())
    await job.start()
    while job._process is None:
        await asyncio.sleep(0)
    now[0] = 4.0
    await asyncio.sleep(0.55)
    await job.pause()
    assert any(m["build"]["state"] == "run" and m["build"]["seconds"] == 4 for m in messages)
