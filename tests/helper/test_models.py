import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from omafindd.models import ModelFile, download, verify


@pytest.fixture
def model_server():
    payload = b'tiny model contents' * 100
    requests = []
    ignore_range = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.path, self.headers.get('Range')))
            offset = 0
            if self.headers.get('Range') and not ignore_range:
                offset = int(self.headers['Range'].removeprefix('bytes=').removesuffix('-'))
            self.send_response(206 if offset else 200)
            if offset:
                self.send_header('Content-Range',
                                 f'bytes {offset}-{len(payload) - 1}/{len(payload)}')
            self.send_header('Content-Length', str(len(payload) - offset))
            self.end_headers()
            self.wfile.write(payload[offset:])

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01})
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', payload, requests, ignore_range
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def model_file(payload, **kwargs):
    return ModelFile('tiny.gguf', kwargs.get('size', len(payload)),
                     kwargs.get('sha256', hashlib.sha256(payload).hexdigest()))


def test_partial_download_resumes_with_range(tmp_path, model_server):
    base_url, payload, requests, _ = model_server
    part = tmp_path / 'tiny.gguf.part'
    part.write_bytes(payload[:13])
    progress = []
    file = model_file(payload)
    download(tmp_path, files=[file], base_url=base_url,
             progress=lambda *args: progress.append(args))
    assert requests[0][1] == 'bytes=13-'
    assert (tmp_path / file.name).read_bytes() == payload
    assert not part.exists()
    assert verify(tmp_path, files=[file]) == {'tiny.gguf': True}
    assert progress[-1] == ('tiny.gguf', len(payload), len(payload))


@pytest.mark.parametrize('fault', ['size', 'sha256'])
def test_invalid_download_is_deleted(tmp_path, model_server, fault):
    base_url, payload, _, _ = model_server
    file = model_file(payload, **{fault: len(payload) + 1 if fault == 'size' else '0' * 64})
    with pytest.raises(ValueError, match=fault):
        download(tmp_path, files=[file], base_url=base_url)
    assert not (tmp_path / file.name).exists()
    assert not (tmp_path / f'{file.name}.part').exists()


def test_f16_is_refused_before_any_download(tmp_path, model_server):
    base_url, payload, requests, _ = model_server
    files = [model_file(payload), ModelFile('model-F16.gguf', 1, '0' * 64)]
    with pytest.raises(ValueError, match='F16'):
        download(tmp_path, files=files, base_url=base_url)
    assert requests == []
    assert list(tmp_path.iterdir()) == []


def test_download_sets_private_permissions(tmp_path, model_server):
    base_url, payload, _, _ = model_server
    file = model_file(payload)
    download(tmp_path, files=[file], base_url=base_url)
    assert (tmp_path / file.name).stat().st_mode & 0o777 == 0o600


def test_valid_existing_file_skips_network(tmp_path, model_server):
    base_url, payload, requests, _ = model_server
    file = model_file(payload)
    (tmp_path / file.name).write_bytes(payload)
    (tmp_path / file.name).chmod(0o644)
    download(tmp_path, files=[file], base_url=base_url)
    assert requests == []
    assert (tmp_path / file.name).stat().st_mode & 0o777 == 0o600


def test_ignored_range_restarts_download(tmp_path, model_server):
    base_url, payload, requests, ignore_range = model_server
    ignore_range.append(True)
    (tmp_path / 'tiny.gguf.part').write_bytes(payload[:13])
    file = model_file(payload)
    download(tmp_path, files=[file], base_url=base_url)
    assert requests[0][1] == 'bytes=13-'
    assert (tmp_path / file.name).read_bytes() == payload


def test_verify_detects_missing_and_corrupted_files(tmp_path):
    file = model_file(b'expected')
    assert verify(tmp_path, files=[file]) == {'tiny.gguf': False}
    (tmp_path / file.name).write_bytes(b'wrong!!!')
    assert verify(tmp_path, files=[file]) == {'tiny.gguf': False}


def test_default_directory_is_resolved_per_call(tmp_path, monkeypatch):
    from omafindd import paths

    file = model_file(b'expected')
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'first'))
    paths.model_dir().mkdir(parents=True)
    (paths.model_dir() / file.name).write_bytes(b'expected')
    assert verify(files=[file]) == {'tiny.gguf': True}
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'second'))
    assert verify(files=[file]) == {'tiny.gguf': False}


def test_complete_partial_file_is_verified_without_network(tmp_path, model_server):
    base_url, payload, requests, _ = model_server
    file = model_file(payload)
    (tmp_path / f'{file.name}.part').write_bytes(payload)
    download(tmp_path, files=[file], base_url=base_url)
    assert requests == []
    assert (tmp_path / file.name).read_bytes() == payload


def test_oversize_partial_file_is_deleted_without_network(tmp_path, model_server):
    base_url, payload, requests, _ = model_server
    file = model_file(payload)
    part = tmp_path / f'{file.name}.part'
    part.write_bytes(payload + b'extra')
    with pytest.raises(ValueError, match='size'):
        download(tmp_path, files=[file], base_url=base_url)
    assert not part.exists()
    assert requests == []


def test_verifier_caches_hash_until_metadata_changes(tmp_path, monkeypatch):
    import os

    from omafindd.models import Verifier

    file = model_file(b'expected')
    path = tmp_path / file.name
    path.write_bytes(b'expected')
    hashes = []
    digest = hashlib.file_digest

    def counted(stream, algorithm):
        hashes.append(stream.name)
        return digest(stream, algorithm)

    monkeypatch.setattr(hashlib, 'file_digest', counted)
    verifier = Verifier(tmp_path, files=[file])
    assert verifier.check() is True
    assert verifier.check() is True
    assert len(hashes) == 1
    assert verifier.files_report() == {
        'tiny.gguf': {'size': 8, 'mtime_ns': path.stat().st_mtime_ns, 'ok': True}}
    before = path.stat()
    path.write_bytes(b'wrong!!!')
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000))
    assert verifier.check() is False
    assert verifier.check() is False
    assert len(hashes) == 2
    path.unlink()
    assert verifier.check() is False
    path.write_bytes(b'expected')
    assert verifier.check() is True
    assert len(hashes) == 3


def test_verifier_rechecks_replaced_inode_with_same_size_and_mtime(tmp_path):
    import os

    from omafindd.models import Verifier

    file = model_file(b'expected')
    path = tmp_path / file.name
    path.write_bytes(b'expected')
    verifier = Verifier(tmp_path, files=[file])
    assert verifier.check() is True
    before = path.stat()
    replacement = tmp_path / 'replacement'
    replacement.write_bytes(b'wrong!!!')
    os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
    replacement.replace(path)
    assert verifier.check() is False


def test_models_verification_import_needs_only_stdlib():
    import subprocess
    import sys
    from pathlib import Path

    result = subprocess.run([sys.executable, '-S', '-c',
                             'import sys; sys.path.insert(0, sys.argv[1]); '
                             'from omafindd.models import Verifier',
                             str(Path(__file__).resolve().parents[2] / 'helper')],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
