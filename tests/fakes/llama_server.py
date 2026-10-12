import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx


class FakeLlamaServer:
    def __init__(self, port=0, api_key='test-key', *, vector=None, health_status=200,
                 reverse=False, ignore_terminate=False):
        self.api_key = api_key
        self.vector = vector
        self.health_status = health_status
        self.reverse = reverse
        self.ignore_terminate = ignore_terminate
        self.requests = []
        self.returncode = None
        self.terminated = False
        self.killed = False
        self._exited = asyncio.Event()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                owner.requests.append((self.path, self.headers.get('Authorization'), None))
                self.send_response(owner.health_status if self.authorized() else 401)
                self.end_headers()

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.requests.append((self.path, self.headers.get('Authorization'), body))
                if not self.authorized() or self.path != '/v1/embeddings':
                    self.send_response(401 if not self.authorized() else 404)
                    self.end_headers()
                    return
                if (body.get('encoding_format') != 'float'
                        or any(not isinstance(row, dict) or 'content' not in row
                               for row in body.get('input', []))):
                    self.send_response(400)
                    self.end_headers()
                    return
                data = []
                for index, _ in enumerate(body['input']):
                    vector = owner.vector
                    if vector is None:
                        vector = [0.0] * 768
                        vector[index] = 1.0
                    data.append({'object': 'embedding', 'index': index, 'embedding': vector})
                if owner.reverse:
                    data.reverse()
                encoded = json.dumps({'object': 'list', 'data': data, 'model': 'fake',
                                      'usage': {'prompt_tokens': 1, 'total_tokens': 1}}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def authorized(self):
                return self.headers.get('Authorization') == f'Bearer {owner.api_key}'

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={'poll_interval': 0.01})
        self.thread.start()

    def terminate(self):
        self.terminated = True
        if not self.ignore_terminate:
            self.close()

    def kill(self):
        self.killed = True
        self.close()

    async def wait(self):
        await self._exited.wait()
        return self.returncode

    def close(self):
        if self.returncode is not None:
            return
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.returncode = 0
        self._exited.set()


class FakeSpawner:
    def __init__(self, **server_options):
        self.server_options = server_options
        self.server_factory = FakeLlamaServer
        self.commands = []
        self.environments = []
        self.servers = []

    async def __call__(self, *argv, **kwargs):
        self.commands.append(list(argv))
        self.environments.append(kwargs.get('env'))
        server = self.server_factory(port=int(argv[argv.index('--port') + 1]),
                                     api_key=kwargs['env']['LLAMA_API_KEY'],
                                     **self.server_options)
        self.servers.append(server)
        return server

    def close(self):
        for server in self.servers:
            server.close()


class MemoryLlamaServer(FakeLlamaServer):
    def __init__(self, port=0, api_key='test-key', *, vector=None, health_status=200,
                 reverse=False, ignore_terminate=False):
        self.api_key = api_key
        self.vector = vector
        self.health_status = health_status
        self.reverse = reverse
        self.ignore_terminate = ignore_terminate
        self.requests = []
        self.returncode = None
        self.terminated = False
        self.killed = False
        self._exited = asyncio.Event()
        self.health_requested = asyncio.Event()
        self.embedding_requested = asyncio.Queue()
        self.embedding_release = asyncio.Event()
        self.embedding_release.set()
        self.request_error = None

    async def handle(self, request):
        body = json.loads(request.content) if request.method == 'POST' else None
        authorization = request.headers.get('Authorization')
        self.requests.append((request.url.path, authorization, body))
        if authorization != f'Bearer {self.api_key}':
            return httpx.Response(401)
        if request.url.path == '/health':
            self.health_requested.set()
            return httpx.Response(self.health_status)
        if request.url.path != '/v1/embeddings':
            return httpx.Response(404)
        self.embedding_requested.put_nowait(body)
        await self.embedding_release.wait()
        if self.request_error is not None:
            raise self.request_error
        data = []
        for index, _ in enumerate(body['input']):
            vector = self.vector
            if vector is None:
                vector = [0.0] * 768
                vector[index] = 1.0
            data.append({'object': 'embedding', 'index': index, 'embedding': vector})
        if self.reverse:
            data.reverse()
        return httpx.Response(200, json={'object': 'list', 'data': data, 'model': 'fake',
                                        'usage': {'prompt_tokens': 1, 'total_tokens': 1}})

    def close(self):
        self.returncode = 0
        self._exited.set()
