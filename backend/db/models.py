"""DB tables."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, BigInteger, Column, DateTime, Index
from sqlalchemy.types import TypeDecorator
from sqlmodel import Field, SQLModel

### Bump when a table or what is stored in it changes, together with a migration in db._MIGRATIONS.
### Without one, an older database stops the start instead of being changed. A new table needs no bump.
### 2: leagues in another game mode than Classic are no longer stored
SCHEMA_VERSION = 2


class UTCDateTime(TypeDecorator):
    """Stores timezone aware datetimes as UTC and always hands them back timezone aware.

    SQLite has no timezone support and would otherwise return naive datetimes.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive datetimes are not allowed, use timezone aware UTC datetimes")
        value = value.astimezone(UTC)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def utcnow() -> datetime:
    return datetime.now(UTC)


def _ts(nullable: bool = True, index: bool = False):
    return Field(default=None, sa_type=UTCDateTime, nullable=nullable, index=index)


def _money(default: int | None = None):
    ### Team values reach several hundred million, beyond a 32 bit integer
    return Field(default=default, sa_type=BigInteger)


### ===============================================================================
### Competition
### ===============================================================================


class Team(SQLModel, table=True):
    id: str = Field(primary_key=True)
    competition_id: int = Field(default=1, index=True)
    name: str
    image: str | None = None
    placement: int | None = None
    points: int | None = None
    matches: int | None = None
    goal_diff: int | None = None
    updated_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)


class Player(SQLModel, table=True):
    id: str = Field(primary_key=True)
    team_id: str | None = Field(default=None, index=True)
    first_name: str | None = None
    last_name: str = ""
    position: int = 0 # 1 goalkeeper, 2 defender, 3 midfielder, 4 forward, 0 unknown
    status: int = 0
    status_text: str | None = None
    market_value: int = _money(0)
    market_value_trend: int = 0 # 0 flat, 1 rising, 2 falling
    total_points: int | None = None
    average_points: int | None = None
    goals: int | None = None
    assists: int | None = None
    image: str | None = None
    active: bool = True # False once the player no longer shows up in any team (left the league)
    details_synced_at: datetime | None = _ts()
    updated_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)


class MarketValueHistory(SQLModel, table=True):
    """One row per player, the history is a list of `[day, value]` pairs, oldest first.

    `day` counts days since 1970-01-01, exactly as Kickbase sends it.
    """
    player_id: str = Field(primary_key=True)
    points: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    synced_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)


class Fixture(SQLModel, table=True):
    id: str = Field(primary_key=True)
    competition_id: int = Field(default=1, index=True)
    day: int = Field(index=True)
    kickoff: datetime | None = _ts()
    team1_id: str | None = None
    team2_id: str | None = None
    team1_goals: int | None = None
    team2_goals: int | None = None
    status: int | None = None
    minute: str | None = None


### ===============================================================================
### League
### ===============================================================================

class League(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    image: str | None = None
    competition_id: int = 1
    current_day: int | None = None
    number_of_days: int | None = None
    season_name: str | None = None
    market_values_updated_at: datetime | None = _ts()
    synced_at: datetime | None = _ts()


class LeagueSeason(SQLModel, table=True):
    """Kickbase reports the start of a league season and its initial money.

    Kickbase moves the date when a league is reset.
    """
    league_id: str = Field(primary_key=True)
    started_at: datetime | None = _ts()
    start_money: int | None = _money()
    transfers_complete_since: datetime | None = _ts() # The stored transfers reach back to this moment


class Manager(SQLModel, table=True):
    league_id: str = Field(primary_key=True)
    id: str = Field(primary_key=True)
    name: str
    image: str | None = None
    placement: int | None = None
    points: int | None = None
    average_points: int | None = None
    team_value: int | None = _money()
    matchday_wins: int | None = None


class SquadEntry(SQLModel, table=True):
    """Which manager owns which player, and what they paid."""
    league_id: str = Field(primary_key=True)
    player_id: str = Field(primary_key=True)
    manager_id: str = Field(index=True)
    purchase_price: int | None = _money()
    market_value_gain: int | None = _money()


class MarketListing(SQLModel, table=True):
    league_id: str = Field(primary_key=True)
    player_id: str = Field(primary_key=True)
    seller_id: str | None = None
    seller_name: str | None = None
    price: int | None = _money()
    offer_count: int | None = None
    expires_at: datetime | None = _ts()
    listed_at: datetime | None = _ts()


class Transfer(SQLModel, table=True):
    """A transfer from a manager's transfer list. Kept forever.

    The ids say who it was. The names are only needed for managers who left before ids were stored.
    """
    __table_args__ = (Index("ix_transfer_league_date", "league_id", "date"),)

    id: str = Field(primary_key=True)
    league_id: str
    date: datetime = Field(sa_type=UTCDateTime)
    player_id: str = Field(index=True)
    player_name: str | None = None
    team_id: str | None = None
    buyer: str | None = None
    buyer_id: str | None = None
    seller: str | None = None
    seller_id: str | None = None
    price: int = _money(0)


class MatchdayRanking(SQLModel, table=True):
    league_id: str = Field(primary_key=True)
    day: int = Field(primary_key=True)
    manager_id: str = Field(primary_key=True)
    points: int | None = None
    season_points: int | None = None
    team_value: int | None = _money()
    placement: int | None = None
    final: bool = False # True once the matchday is over


class Battle(SQLModel, table=True):
    league_id: str = Field(primary_key=True)
    type: int = Field(primary_key=True)
    name: str
    description: str = ""
    sort_order: int = 0


class BattleEntry(SQLModel, table=True):
    league_id: str = Field(primary_key=True)
    type: int = Field(primary_key=True)
    manager_id: str = Field(primary_key=True)
    placement: int | None = None
    value: float | None = None


class SyncRun(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    league_id: str | None = None
    trigger: str = "schedule" # startup, schedule, login or manual
    triggered_by: str | None = None
    status: str = "running" # running, success or failed
    started_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime, index=True)
    finished_at: datetime | None = _ts()
    requests: int = 0
    error: str | None = None
    stats: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))


### ===============================================================================
### Users
### ===============================================================================

class User(SQLModel, table=True):
    """A Kickbase account that logged, or the account from the environment."""
    id: str = Field(primary_key=True)
    name: str
    email: str | None = None
    image: str | None = None
    last_login_at: datetime | None = _ts()


class UserLeague(SQLModel, table=True):
    """Which leagues a user is in, and their real budget there. Only shown to the user themselves."""
    user_id: str = Field(primary_key=True)
    league_id: str = Field(primary_key=True, index=True)
    budget: int | None = _money()
    budget_updated_at: datetime | None = _ts()
    ### Personal settings, they change nothing at Kickbase
    inactive: bool = False # Only for this user, the league stays reachable
    analysis_squad_limit: int | None = None # None: KBI_AUTOMATION__MAX_SQUAD_SIZE
    analysis_club_limit: int | None = None # None: coach.MAX_PER_CLUB


class UserSession(SQLModel, table=True):
    """A login. The id is the SHA-256 of the cookie value, the Kickbase token is stored encrypted."""
    id: str = Field(primary_key=True)
    user_id: str = Field(index=True)
    token_encrypted: str
    token_expires_at: datetime = Field(sa_type=UTCDateTime)
    created_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)
    expires_at: datetime = Field(sa_type=UTCDateTime, index=True)
    last_seen_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)


class MarketBid(SQLModel, table=True):
    """A user's own offer for a player on the market."""
    league_id: str = Field(primary_key=True)
    user_id: str = Field(primary_key=True)
    player_id: str = Field(primary_key=True)
    price: int = _money(0)


class SchemaInfo(SQLModel, table=True):
    id: int = Field(default=1, primary_key=True)
    version: int


### ===============================================================================
### Manager tools (automation, forecasts, push). New tables only, so no schema bump is needed.
### ===============================================================================

class UserAutomation(SQLModel, table=True):
    """What a user lets the app do for them in one league. Everything is off until they switch it on."""
    user_id: str = Field(primary_key=True)
    league_id: str = Field(primary_key=True)
    ### Put players with a forecast of at least `scout_threshold` on the Kickbase scouting list
    auto_scout: bool = False
    scout_threshold: int = _money(250_000)
    ### At most this many players are put on the list by the app
    scout_limit: int = 30
    ### Keep the best eleven saved at Kickbase whenever the lineup can be changed
    auto_lineup: bool = False
    ### Push warnings before the deadline (negative budget, gaps or unavailable players in the eleven)
    deadline_alerts: bool = True
    ### Push when a transfer target or a bargain is listed, and when a rival has to sell
    listing_alerts: bool = True
    ### Push a daily sell advice before the market value update
    sell_alerts: bool = True
    ### Autotrader (sync/trader.py): bids and sells on its own for a better eleven and for profit
    trader: bool = False
    ### Off: a dry run that only logs and pushes what it would do
    trader_live: bool = False
    ### Also trade for market value profit between matchdays, not only for the eleven
    trader_profit: bool = True
    ### Thresholds and limits, see core.trader.Options. Missing keys use its defaults
    trader_options: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False, server_default="{}"))
    updated_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)


class AutoScout(SQLModel, table=True):
    """A player the app put on a user's scouting list. Only these are ever taken off again by the app."""
    user_id: str = Field(primary_key=True)
    league_id: str = Field(primary_key=True)
    player_id: str = Field(primary_key=True)
    added_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)
    ### The user took the player off by hand: not added again until the forecast drops below the threshold
    dismissed: bool = False


class PlayerForm(SQLModel, table=True):
    """Points of a player's matches this season from `/performance`, as `[day, points, minutes]`,
    newest first. Matches the player did not play in have 0 points."""
    player_id: str = Field(primary_key=True)
    matches: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    synced_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)


class ForecastLog(SQLModel, table=True):
    """A market value forecast and, once it is known, the real change. Shows how good the forecasts are."""
    player_id: str = Field(primary_key=True)
    day: int = Field(primary_key=True) # The market value day the forecast is for
    predicted: int = _money(0)
    actual: int | None = _money()


class AutomationEvent(SQLModel, table=True):
    """What the automation did or tried, per user. Also remembers which deadline alerts were sent."""
    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)
    league_id: str = Field(index=True)
    at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime, index=True)
    kind: str # lineup, scout, alert, sell, push
    key: str | None = Field(default=None, index=True) # Deduplicates alerts, e.g. "alert:14:60"
    ok: bool = True
    message: str = ""
    details: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))


class PushSubscription(SQLModel, table=True):
    """A browser or home screen app that receives push messages. The id is the SHA-256 of the endpoint."""
    id: str = Field(primary_key=True)
    user_id: str = Field(index=True)
    endpoint: str
    p256dh: str
    auth: str
    created_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)


class BidHistory(SQLModel, table=True):
    """Every own bid a user had, kept after the auction. With the transfers it shows lost auctions."""
    league_id: str = Field(primary_key=True)
    user_id: str = Field(primary_key=True)
    player_id: str = Field(primary_key=True)
    price: int = _money(0)
    first_seen: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)
    last_seen: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime, index=True)


class MatchOdds(SQLModel, table=True):
    """Betting odds of a match (decimal, home / draw / away), from Kickbase or The Odds API."""
    match_id: str = Field(primary_key=True)
    home: float | None = None
    draw: float | None = None
    away: float | None = None
    source: str = ""
    raw: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    updated_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)


class MarketSeen(SQLModel, table=True):
    """Listings the market watch has already reported, so a new one is pushed only once."""
    league_id: str = Field(primary_key=True)
    player_id: str = Field(primary_key=True)
    seller_id: str | None = None
    price: int | None = _money()
    seen_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)


class MatchdayLineup(SQLModel, table=True):
    """The eleven a manager fielded on a matchday, from the matchday's ranking."""
    league_id: str = Field(primary_key=True)
    day: int = Field(primary_key=True)
    manager_id: str = Field(primary_key=True)
    players: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))


class TradeLog(SQLModel, table=True):
    """A bid or sale of the autotrader, its outcome and profit. Feeds the learning and the week stats."""
    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)
    league_id: str = Field(index=True)
    player_id: str = Field(index=True)
    at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime, index=True)
    kind: str # bid or sell
    purpose: str # lineup, profit, room (sold to make room), rescue (negative budget), turn (forecast turned)
    ### planned (dry run), open, won, lost, expired, sold
    status: str = "open"
    price: int = _money(0) # The bid, or what a sale brought
    market_value: int = _money(0)
    paid: int | None = _money() # What a won bid finally cost
    profit: int | None = _money() # Of a sale: received minus what the trader paid
    points_gain: float = 0 # Expected points the eleven gains with a lineup purchase
    resolved_at: datetime | None = _ts()
    details: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))


class TraderDebug(SQLModel, table=True):
    """One autotrader round's inputs and decisions, stored when they changed. Kept for a few weeks for
    the export."""
    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)
    league_id: str = Field(index=True)
    at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime, index=True)
    data: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))


class ShadowTrade(SQLModel, table=True):
    """A trade on paper: a purchase the trader passed on (or could not make), followed as if it had
    bid, or a real sale, followed to see what the player did afterwards. Teaches the trader."""
    id: int | None = Field(default=None, primary_key=True)
    league_id: str = Field(index=True)
    ### Whose trader started it: only that user sees it. "" for paper trades from before this column
    user_id: str = Field(default="", index=True)
    player_id: str = Field(index=True)
    at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime, index=True)
    kind: str # buy or sell
    purpose: str # Why it was considered: profit, lineup, cover; for a sale the sale's purpose
    ### buy: watching (auction running), holding (would have won), lost, expired, done; sell: watching, done
    status: str = "watching"
    bid: int = _money(0) # The bid it would have placed
    market_value: int = _money(0) # When decided
    forecast_gain: int = _money(0) # The forecast gain over the holding time when decided
    free_agent: bool = False # Listed by Kickbase: without a transfer the bid would have won
    paid: int | None = _money()
    won_day: int | None = None # Market value day the purchase would have happened
    winner_price: int | None = _money()
    value_after: int | None = _money()
    result: int | None = _money() # buy: profit on paper; sell: market value change after the sale
    resolved_at: datetime | None = _ts()


### ===============================================================================
### Learning
### ===============================================================================

class ForecastObservation(SQLModel, table=True):
    """A player's market value forecast as the trader saw it on a market value day, and later what the
    value really did (E10.00). Every squad and market player of a league once per day, so the forecast
    is checked on all of them, not only on the trader's own buys. Added without a schema version (ADR-010)."""
    league_id: str = Field(primary_key=True)
    player_id: str = Field(primary_key=True)
    day: int = Field(primary_key=True) # Market value day in force when observed (days since 1970-01-01)
    observed_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)
    value: int = _money(0)
    forecast_1: int = _money(0) # Forecast change after the next update, unscaled
    forecast_2: int = _money(0) # ... after two updates
    actual_1: int | None = _money() # What the value really did after one update, None while unknown
    actual_2: int | None = _money()
    resolved: bool = Field(default=False, index=True) # Both horizons known, or given up


class ModelState(SQLModel, table=True):
    """What the app learned, e.g. "expectation" weights, "bidder" model, "achievement_mode"."""
    key: str = Field(primary_key=True)
    data: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    updated_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)


class ExpectationLog(SQLModel, table=True):
    """The expected points of a player for a matchday as known before it, and later what he scored."""
    competition_id: int = Field(primary_key=True)
    day: int = Field(primary_key=True)
    player_id: str = Field(primary_key=True)
    expected: float = 0
    form: float | None = None
    average: float | None = None
    chance: float = 1 # Chance to play times availability
    win: float | None = None
    table: float = 0
    home: bool | None = None
    actual: int | None = None
    logged_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)


class AchievementSnapshot(SQLModel, table=True):
    """The user's own achievement counters as Kickbase reports them, taken after every sync."""
    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)
    league_id: str = Field(index=True)
    at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)
    last_final_day: int | None = None # The last finished matchday at that moment
    counts: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    raw: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))


class AuctionLog(SQLModel, table=True):
    """A listing with what every manager looked like when it appeared, and who got the player."""
    league_id: str = Field(primary_key=True)
    player_id: str = Field(primary_key=True)
    listed_at: datetime = Field(primary_key=True, sa_type=UTCDateTime)
    seller_id: str | None = None
    market_value: int = _money(0)
    price: int | None = _money()
    position: int = 0
    team_id: str | None = None
    ### Per manager: need, interest, activity, squad_full, can_buy, affordable
    candidates: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    winner_id: str | None = None
    final_price: int | None = _money()
    resolved: bool = False
