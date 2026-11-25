"""Only one process per database runs the automation: a second process cannot take the leader lease
while the first holds it, and takes over once the first is gone. Run from backend/:
python tests/check_leader.py"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import create_db_engine, try_lease  # noqa: E402

HOLDER = r'''
import sys, time
sys.path.insert(0, sys.argv[1])
from db import create_db_engine, try_lease
lease = try_lease(create_db_engine("sqlite:///" + sys.argv[2]), "automation-leader")
print("held" if lease else "busy", flush=True)
time.sleep(float(sys.argv[3]))
'''


def main() -> None:
    folder = Path(tempfile.mkdtemp())
    path = folder / "kickbase.db"
    backend = Path(__file__).resolve().parent.parent
    script = folder / "holder.py"
    script.write_text(HOLDER, encoding="utf-8")

    first = subprocess.Popen([sys.executable, str(script), str(backend), str(path), "3"], stdout=subprocess.PIPE, text=True)
    assert first.stdout.readline().strip() == "held", "the first process takes the lease"
    engine = create_db_engine(f"sqlite:///{path}")
    assert try_lease(engine, "automation-leader") is None, "a second process cannot take it while the first lives"
    first.wait(timeout=10)
    deadline = time.time() + 5
    lease = None
    while lease is None and time.time() < deadline:
        lease = try_lease(engine, "automation-leader")
        time.sleep(0.1)
    assert lease is not None, "after the first process ended, the second takes over"
    second = subprocess.run([sys.executable, str(script), str(backend), str(path), "0"], capture_output=True, text=True, timeout=20)
    assert second.stdout.strip() == "busy", "while this process leads, another one only serves the API"
    lease.release()
    third = subprocess.run([sys.executable, str(script), str(backend), str(path), "0"], capture_output=True, text=True, timeout=20)
    assert third.stdout.strip() == "held", "a released lease is free again"
    assert try_lease(create_db_engine("sqlite://"), "automation-leader") is not None, "in memory: one process, always the leader"
    print("PASS: one automation leader per database, takeover when it is gone")


if __name__ == "__main__":
    main()
