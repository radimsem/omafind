import json
import os
import sys
from multiprocessing import resource_tracker

from omafindd.jobs import _pool

if __name__ == "__main__":
    with _pool() as pool:
        worker = pool.submit(os.getpid).result(timeout=5)
        print(json.dumps([worker, resource_tracker._resource_tracker._pid]), flush=True)
        sys.stdin.read()
