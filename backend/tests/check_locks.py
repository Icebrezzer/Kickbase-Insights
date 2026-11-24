"""Two processes on one SQLite file: the second waits for the store lock of the first."""

import multiprocessing
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import create_db_engine, exclusive

HOLD = 1.5


def hold(url: str, ready) -> None:
    with exclusive(create_db_engine(url), "store"):
        ready.set()
        time.sleep(HOLD)


def main():
    with tempfile.TemporaryDirectory() as folder:
        url = f"sqlite:///{folder}/kickbase.db"
        ready = multiprocessing.Event()
        other = multiprocessing.Process(target=hold, args=(url, ready))
        other.start()
        assert ready.wait(10), "the other process did not get the lock"
        started = time.monotonic()
        with exclusive(create_db_engine(url), "store"):
            waited = time.monotonic() - started
        other.join()
        assert waited > HOLD / 2, f"took the lock while another process held it ({waited:.2f}s)"

        ### Another name is another lock
        ready.clear()
        other = multiprocessing.Process(target=hold, args=(url, ready))
        other.start()
        assert ready.wait(10)
        started = time.monotonic()
        with exclusive(create_db_engine(url), "analysis"):
            assert time.monotonic() - started < HOLD / 2
        other.join()

    with exclusive(create_db_engine("sqlite://"), "store"):
        pass
    print("PASS: the store lock is shared between processes")


if __name__ == "__main__":
    main()
