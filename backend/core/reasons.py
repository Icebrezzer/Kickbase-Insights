"""Reason codes of the autotrader's decisions on market players (E01.02).

Every market player of a round gets one primary code and any number of secondary ones, so a log, an
export or the UI can count and explain them without parsing German text. The risk engine keeps its own
codes (core/risk.py); a bid it blocked is RISK_BLOCKED here with the risk code as secondary one.

Codes are stable: never rename one, only add new ones.
"""

from __future__ import annotations

from core import trader as t

### Not a candidate at all
OWN_BID_OPEN = "OWN_BID_OPEN"
OWN_PLAYER = "OWN_PLAYER"
REBUY_BLOCK = "REBUY_BLOCK"
UNCONFIRMED_ACTION = "UNCONFIRMED_ACTION"
CLUB_LIMIT = "CLUB_LIMIT"
NO_MARKET_DATA = "NO_MARKET_DATA"
AUCTION_EXPIRED = "AUCTION_EXPIRED"
### No purpose fits
NOT_FIT = "NOT_FIT"
PROFIT_TRADING_OFF = "PROFIT_TRADING_OFF"
STOP_LOSS = "STOP_LOSS"
FORECAST_PAUSE = "FORECAST_PAUSE"
PHASE_FINAL = "PHASE_FINAL"
AUCTION_END_UNKNOWN = "AUCTION_END_UNKNOWN"
NO_RISING_FORECAST = "NO_RISING_FORECAST"
### Why he is no lineup upgrade (secondary next to the profit reason)
PLAY_RATE_UNKNOWN = "PLAY_RATE_UNKNOWN"
PLAY_RATE_LOW = "PLAY_RATE_LOW"
NO_ELEVEN_GAIN = "NO_ELEVEN_GAIN"
GAIN_BELOW_MIN = "GAIN_BELOW_MIN"
QUALITY_UNKNOWN = "QUALITY_UNKNOWN"
QUALITY_EDGE = "QUALITY_EDGE"
LOOKAHEAD_WORSE = "LOOKAHEAD_WORSE"
### A purpose fits, but no bid this round
DAILY_BIDS = "DAILY_BIDS"
SLOT_TAKEN = "SLOT_TAKEN"
ELEVEN_GAPS_FIRST = "ELEVEN_GAPS_FIRST"
COVER_DONE = "COVER_DONE"
SQUAD_FULL = "SQUAD_FULL"
NO_PRICE = "NO_PRICE"
FALLING_TODAY = "FALLING_TODAY"
MARGIN_BELOW_MIN = "MARGIN_BELOW_MIN"
ROI_BELOW_MIN = "ROI_BELOW_MIN"
PRICE_PER_POINT = "PRICE_PER_POINT"
COVER_PRICE = "COVER_PRICE"
PROFIT_ROOM = "PROFIT_ROOM"
BUDGET = "BUDGET"
ROOM_SALE_WINDOW = "ROOM_SALE_WINDOW"
ROOM_SALE_NONE = "ROOM_SALE_NONE"
ROOM_SALE_NOT_ENOUGH = "ROOM_SALE_NOT_ENOUGH"
### Outcome
BID_PLANNED = "BID_PLANNED"
RISK_BLOCKED = "RISK_BLOCKED"
NOT_CHECKED = "NOT_CHECKED"

TEXT: dict[str, str] = {
    OWN_BID_OPEN: "eigenes Gebot offen",
    OWN_PLAYER: "eigener Spieler",
    REBUY_BLOCK: "vor kurzem verkauft",
    UNCONFIRMED_ACTION: "Status eines früheren Aufrufs unklar",
    CLUB_LIMIT: "Vereinslimit",
    NO_MARKET_DATA: "keine Marktdaten",
    AUCTION_EXPIRED: "Auktion abgelaufen",
    NOT_FIT: "verletzt/fraglich",
    PROFIT_TRADING_OFF: "Gewinnhandel aus",
    STOP_LOSS: "Gewinnhandel pausiert (Stop-Loss)",
    FORECAST_PAUSE: "Gewinnhandel pausiert (Prognose zuletzt unzuverlässig)",
    PHASE_FINAL: "letzte Stunde vor dem Spieltag",
    AUCTION_END_UNKNOWN: "Auktionsende unbekannt",
    NO_RISING_FORECAST: "keine steigende Prognose",
    PLAY_RATE_UNKNOWN: "Einsatzquote unbekannt",
    PLAY_RATE_LOW: "Einsatzquote zu niedrig",
    NO_ELEVEN_GAIN: "macht die Elf nicht besser",
    GAIN_BELOW_MIN: "Punkte-Plus unter dem Minimum",
    QUALITY_UNKNOWN: "kein Punkteschnitt und keine Form",
    QUALITY_EDGE: "Punkteschnitt nicht genug besser als der Verdrängte",
    LOOKAHEAD_WORSE: "nächste 3 Spiele schlechter als der Verdrängte",
    DAILY_BIDS: "Tageslimit Gebote erreicht",
    SLOT_TAKEN: "Platz schon durch ein Gebot dieser Runde besetzt",
    ELEVEN_GAPS_FIRST: "erst die Startelf füllen",
    COVER_DONE: "Position schon abgedeckt",
    SQUAD_FULL: "kein Kaderplatz frei",
    NO_PRICE: "kein gültiger Preis",
    FALLING_TODAY: "Marktwert heute gefallen",
    MARGIN_BELOW_MIN: "Netto-Gewinn unter der Mindestmarge",
    ROI_BELOW_MIN: "Netto-Rendite unter dem Minimum",
    PRICE_PER_POINT: "Preis je Punkt zu hoch",
    COVER_PRICE: "teurer als der Höchstpreis für Ersatz",
    PROFIT_ROOM: "Rahmen für Gewinnhandel ausgeschöpft",
    BUDGET: "Budget zu knapp",
    ROOM_SALE_WINDOW: "Verkauf erst im Verkaufsfenster",
    ROOM_SALE_NONE: "kein Spieler, der auch ohne den Neuzugang verzichtbar ist",
    ROOM_SALE_NOT_ENOUGH: "auch mit Verkauf nicht",
    BID_PLANNED: "Gebot geplant",
    RISK_BLOCKED: "von der Risikoprüfung blockiert",
    NOT_CHECKED: "nicht geprüft",
    ### The money limits of core.trader.money_check, named as secondary reasons of BUDGET
    t.LIMIT_RESERVE: "Reserve",
    t.LIMIT_DEBT: "Kontostand im Minus",
    t.LIMIT_LIQUIDATION: "Kredit nur so weit, wie Verkäufe ihn zurückzahlen",
    t.LIMIT_CREDIT_MODE: "Kreditmodus gibt diesem Zweck keinen Kredit",
    t.LIMIT_PHASE: "kurz vor dem Spieltag kein Kredit",
    ### t.LIMIT_PROFIT_ROOM is the code PROFIT_ROOM above
}


def price_blockers(c: t.Candidate, purpose: str, upgrade: t.Upgrade | None, money: int, opts: t.Options,
                   min_margin: int, ratio: float, profit_room: int) -> list[str]:
    """Every limit the minimum bid for `c` breaks, the economic ones first: when a buy does not pay,
    more money would not change that. Mirrors the caps of the bid pricing (sync.trader._price), checked
    at the lowest possible bid, so each code is a cause on its own and not "margin or budget"."""
    low = t.bid_for(c, 0.0, None)
    if low is None:
        return [NO_PRICE]
    economic: list[str] = []
    other: list[str] = []
    if purpose == "profit":
        if not c.fit or c.forecast <= 0:
            economic.append(NO_RISING_FORECAST)
        elif c.today < 0:
            economic.append(FALLING_TODAY)
        else:
            net = t.expected_profit(c, low, ratio)
            if net < min_margin:
                economic.append(MARGIN_BELOW_MIN)
            if net < low * opts.min_roi / 100:
                economic.append(ROI_BELOW_MIN)
        if profit_room < low:
            other.append(PROFIT_ROOM)
    if upgrade is not None:
        worth = int(upgrade.replaced_value * ratio + opts.max_cost_per_point * max(upgrade.gain, 0.1))
        if worth < low or not t.worth_it(upgrade, low, opts, ratio):
            economic.append(PRICE_PER_POINT)
    if purpose == "cover" and opts.cover_max_price < low:
        economic.append(COVER_PRICE)
    cash = money if purpose == "profit" else int(money * opts.lineup_share / 100)
    if cash < low:
        other.append(BUDGET)
    return economic + other or [NO_PRICE]


def money_limits(check: dict | None, purpose: str) -> list[str]:
    """The money limits of a purpose, largest first: what keeps the released budget below the max bid."""
    limits = ((check or {}).get("limits") or {}).get(purpose) or {}
    return [code for code, amount in sorted(limits.items(), key=lambda item: -item[1]) if amount > 0]


### ===============================================================================
### Statistics over the stored rounds (E01.03)
### ===============================================================================

### Rounds from before E01.02 carry only a text
LEGACY = "LEGACY_TEXT"
TEXT[LEGACY] = "Runde vor Einführung der Codes"
WINDOWS = (1, 7, 21)


def rejection_stats(rounds: list[tuple[object, dict]], now: object, day_of, windows: tuple[int, ...] = WINDOWS) -> dict:
    """Per window of days: rounds, players checked, players with a planned bid, players without, and how
    often each code was the primary or a secondary reason. Counted once per player, day and code, so a
    player rejected in 200 rounds of one day counts once. `rounds` are (time, debug data) of planning
    rounds, `day_of` turns a time into a local day number, `now` the same for the windows."""
    today = day_of(now)
    result: dict[str, dict] = {}
    for window in windows:
        start = today - window + 1
        checked: set[str] = set()
        bid: set[str] = set()
        primary: dict[str, set[tuple[str, int]]] = {}
        secondary: dict[str, set[tuple[str, int]]] = {}
        count = 0
        for at, data in rounds:
            day = day_of(at)
            if day < start or data.get("rescue"):
                continue
            count += 1
            for m in data.get("market", []):
                pid = str(m.get("id"))
                checked.add(pid)
                code = m.get("reason") or LEGACY
                if code == BID_PLANNED:
                    bid.add(pid)
                primary.setdefault(code, set()).add((pid, day))
                for extra in m.get("reasons") or []:
                    secondary.setdefault(extra, set()).add((pid, day))
        rank = lambda found: dict(sorted(((c, len(v)) for c, v in found.items()), key=lambda item: -item[1]))  # noqa: E731
        result[f"d{window}"] = {
            "rounds": count, "checked": len(checked), "with_bid": len(bid), "without_bid": len(checked - bid),
            "primary": rank(primary), "secondary": rank(secondary),
        }
    return result
