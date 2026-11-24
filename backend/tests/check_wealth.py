"""Financial regression: trades conserve wealth, missing values stay unknown, rights hold."""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.insights import Insights
from api.schemas import ChartManager
from core import analytics


class Fixture(Insights):
    def __init__(self):
        self.viewer_id = "a"
        self.season = SimpleNamespace(start_money=100)
        self.now = datetime.now(UTC)
        self.first = analytics.market_value_day(self.now - timedelta(days=5))
        self.history = [[self.first, 50]]
        self.records = [
            analytics.TransferRecord("1", self.now - timedelta(days=3), "p", "P", None, "a", None, 50)
        ]

    def season_start(self):
        return self.now - timedelta(days=5)

    def _chart_managers(self):
        return [ChartManager(id="a", name="A"), ChartManager(id="b", name="B")]

    def _transfer_records(self):
        return self.records

    def _squad(self):
        return {"p": SimpleNamespace(manager_id="a")} if len(self.records) == 1 else {}

    def _histories(self, ids):
        return {"p": self.history}


def main():
    fixture = Fixture()
    private = fixture.wealth_chart(False)
    assert [m.id for m in private.managers] == ["a"]
    assert all("b" not in row for row in private.rows)
    assert all(row["a"] == 100 for row in private.rows), "Purchase must not create a wealth jump"
    assert all(row["b"] == 100 for row in fixture.wealth_chart(True).rows)
    fixture.records.append(
        analytics.TransferRecord("2", fixture.now - timedelta(days=1), "p", "P", None, None, "a", 70)
    )
    rows = fixture.wealth_chart(True).rows
    assert rows[0]["a"] == 100 and rows[-1]["a"] == 120
    fixture.history = []
    rows = fixture.wealth_chart(False).rows
    assert any(row["a"] is None for row in rows), "Unknown squad value must not become zero"
    assert rows[-1]["a"] == 120, "Empty squad has known zero value"
    fixture.season.start_money = 0
    assert fixture.wealth_chart(False).rows[0]["a"] == 0, "A configured zero starting balance is valid"
    print("PASS: purchases, realized gain, missing history, zero start money and viewer isolation")


if __name__ == "__main__":
    main()
