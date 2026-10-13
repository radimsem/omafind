import subprocess
from concurrent.futures import Future


def command(*args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, timeout=30, **kwargs).stdout


def tone(path, seconds, *, silent=False):
    source = "anullsrc=r=16000:cl=mono" if silent else "sine=frequency=440:sample_rate=16000"
    command("ffmpeg", "-v", "error", "-threads", "1", "-f", "lavfi", "-i", source,
            "-t", str(seconds), "-y", str(path))
    return path


def video(path, *, shots=False, audio=False):
    source = "color=black:s=320x180:r=2:d=12"
    if shots:
        source = ";".join(
            f"color=black:s=320x180:r=2:d=3,"
            f"drawbox=x={80 * index}:y=32:w=80:h=100:color=white:t=fill[v{index}]"
            for index in range(4)
        ) + ";[v0][v1][v2][v3]concat=n=4:v=1:a=0"
    args = ["ffmpeg", "-v", "error", "-filter_threads", "1", "-f", "lavfi", "-i", source]
    if audio:
        args += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000:duration=12"]
    command(*args, "-threads", "1", "-c:v", "mpeg4", "-y", str(path))
    return path


class InlinePool:
    def __init__(self, **kwargs):
        pass

    def submit(self, function, *args):
        future = Future()
        try:
            future.set_result(function(*args))
        except Exception as error:
            future.set_exception(error)
        return future

    def shutdown(self, **kwargs):
        pass
