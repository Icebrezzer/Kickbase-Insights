"""Upgrade check: a database written by an older release opens with this one, nothing is lost.

    python tests/check_trader_migration.py <backend folder of the old release>

Step 1 runs in a child process with the old code: it creates the database and stores trader settings,
a learned state, trades and paper trades as that release wrote them. Step 2 opens the same file with
this code and checks the new columns, the stored values and the trader functions on them.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

OLD = r'''
import sys
sys.path.insert(0, sys.argv[1])
from sqlmodel import Session
from db import create_db_engine, init_db
from db.models import ModelState, ShadowTrade, TradeLog, UserAutomation
engine = create_db_engine("sqlite:///" + sys.argv[2])
init_db(engine)
with Session(engine) as s:
    s.add(UserAutomation(user_id="1001", league_id="4242", trader=True, trader_live=True,
                         trader_options={"min_gain": 3.5, "profit_share": 40, "shadow": False}))
    s.add(ModelState(key="trader", data={"extra": [0.2, 0.4, 0.6], "min_margin": 180000, "won": 5, "lost": 2,
                                          "gain_ratio": 0.8, "gain_samples": 12, "swap_edge": 90000}))
    s.add(TradeLog(user_id="1001", league_id="4242", player_id="7", kind="bid", purpose="profit", status="won",
                   price=1000000, paid=1000000, market_value=950000))
    s.add(TradeLog(user_id="1001", league_id="4242", player_id="8", kind="sell", purpose="turn", status="sold",
                   price=900000, market_value=1000000, profit=-100000))
    s.add(ShadowTrade(league_id="4242", player_id="9", kind="buy", purpose="profit", bid=1000000, market_value=1000000))
    s.commit()
print("old release wrote the database")
'''


def main() -> None:
    old_backend = Path(sys.argv[1]).resolve()
    path = Path(tempfile.mkdtemp()) / "kickbase.db"
    script = Path(tempfile.mkdtemp()) / "old_release.py"
    script.write_text(OLD, encoding="utf-8")
    ### -I: the old release's folder is only on the path the script adds, nothing from here leaks in
    done = subprocess.run([sys.executable, "-I", str(script), str(old_backend), str(path)], capture_output=True, text=True, cwd=old_backend)
    assert done.returncode == 0, done.stderr[-2000:]
    print(done.stdout.strip())

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from sqlalchemy import inspect
    from sqlmodel import Session, select

    from core import trader as t
    from db import create_db_engine, init_db
    from db.models import ModelState, ShadowTrade, TradeLog, TraderDebug, UserAutomation

    engine = create_db_engine(f"sqlite:///{path}")
    init_db(engine)
    init_db(engine) # A second start changes nothing
    columns = {c["name"] for c in inspect(engine).get_columns("shadowtrade")}
    assert "user_id" in columns, columns
    assert "traderdebug" in inspect(engine).get_table_names()
    with Session(engine) as s:
        row = s.get(UserAutomation, ("1001", "4242"))
        assert row.trader and row.trader_live, "switches kept"
        opts = t.Options.load(row.trader_options)
        assert (opts.min_gain, opts.profit_share, opts.shadow) == (3.5, 40, False), opts
        assert (opts.min_roi, opts.credit_mode, opts.trailing_stop) == (2.0, 1, 5), "new options take their defaults"
        learned = t.Learned.load(s.get(ModelState, "trader").data)
        assert (learned.extra, learned.min_margin, learned.won, learned.swap_edge) == ((0.2, 0.4, 0.6), 180000, 5, 90000), learned
        assert learned.forecast_pause == 0 and learned.direction_hits == 0, "new learned fields start at their defaults"
        assert t.blend(learned, t.Learned()).extra == learned.extra, "the old values are the global base of every league"
        trades = s.exec(select(TradeLog)).all()
        assert {(r.kind, r.status) for r in trades} == {("bid", "won"), ("sell", "sold")}, "trades kept"
        shadow = s.exec(select(ShadowTrade)).one()
        assert shadow.user_id == "" and shadow.status == "watching", "old paper trades kept, owned by nobody"
        assert s.exec(select(TraderDebug)).all() == []
    weeks = t.weekly([t.Trade(r.at, r.kind, r.status, r.price, r.paid, r.profit) for r in trades])
    assert weeks[0]["profit"] == -100000 and weeks[0]["won"] == 1, weeks
    print("PASS: a database of the old release opens, settings, learning, trades and paper trades kept")


if __name__ == "__main__":
    main()
