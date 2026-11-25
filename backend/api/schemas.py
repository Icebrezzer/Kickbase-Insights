"""Response models of the REST API. Serialized in camelCase for the frontend."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field
from pydantic.alias_generators import to_camel

from core import analytics
from core.analytics import FairRating, MatchState, PlayerRole


class Schema(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class LeagueOut(Schema):
    id: str
    name: str
    image: str | None = None
    current_day: int | None = None
    number_of_days: int | None = None
    season_name: str | None = None
    synced_at: datetime | None = None
    market_values_updated_at: datetime | None = None
    inactive: bool = False
    analysis_squad_limit: int = 18
    analysis_club_limit: int = 3


class LeaguePreferenceIn(Schema):
    inactive: bool | None = None
    analysis_squad_limit: int | None = Field(default=None, ge=11, le=100)
    analysis_club_limit: int | None = Field(default=None, ge=1, le=100)


class LoginIn(Schema):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class UserOut(Schema):
    id: str
    name: str
    image: str | None = None


class MeOut(Schema):
    user: UserOut
    leagues: list[LeagueOut] # The viewer's leagues, the preferred one first
    balances: bool = False # See the other managers estimated balances (KBI_ALLOW__BALANCES)


class SyncRunOut(Schema):
    id: int
    league_id: str | None = None
    trigger: str
    triggered_by: str | None = None
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    requests: int = 0
    error: str | None = None
    stats: dict = {}


class SyncStatus(Schema):
    running: bool
    next_run: datetime | None = None
    last_run: SyncRunOut | None = None
    last_success_at: datetime | None = None


class StatusOut(Schema):
    version: str
    demo: bool
    authenticated: bool
    league: LeagueOut | None = None
    own_manager_id: str | None = None # The manager id of whoever is looking
    start_date: datetime | None = None
    start_money: int
    sync: SyncStatus
    live_now: bool = False # A real match is running, judged by kick-off times and Kickbase's last live answer
    warnings: list[str] = []


class SyncTriggerOut(Schema):
    started: bool
    reason: str | None = None


class TeamOut(Schema):
    id: str
    name: str
    image: str | None = None
    placement: int | None = None
    points: int | None = None
    matches: int | None = None
    goal_diff: int | None = None


class PlayerOut(Schema):
    id: str
    first_name: str | None = None
    last_name: str
    team_id: str | None = None
    image: str | None = None
    position: int
    status: int
    status_text: str | None = None
    market_value: int
    trend: int
    total_points: int | None = None
    average_points: int | None = None
    goals: int | None = None
    assists: int | None = None
    active: bool = True
    today: int | None = None
    yesterday: int | None = None
    two_days: int | None = None
    seven_days: int | None = None
    thirty_days: int | None = None
    owner_id: str | None = None
    purchase_price: int | None = None
    on_market: bool = False
    ### Expected change of the next market value update and the projection for the following ones
    forecast: int | None = None
    projection: list[int] = []


class BidAdviceOut(Schema):
    amounts: list[int] # The suggested bids, lowest first
    comparable: list[float] # What the others paid on top, lowest first
    similar: bool # comparable purchases of a similar market value


class RivalOut(Schema):
    manager_id: str
    name: str
    image: str | None = None
    club_players: int # Players of this club the manager owns already
    squad_size: int = 0
    estimated_balance: int | None = None
    max_bid: int | None = None
    probability: float = 0 # That he bids, estimated from his habits, needs and money
    expected_bid: int | None = None # What he would probably bid
    reasons: list[str] = []
    in_minus: bool = False # Estimated balance below zero


class MarketPlayerOut(PlayerOut):
    seller_id: str | None = None
    seller_name: str | None = None
    price: int | None = None
    offer_count: int | None = None
    own_bid: int | None = None
    expires_at: datetime | None = None
    listed_at: datetime | None = None
    is_free_agent: bool = True
    bid_advice: BidAdviceOut | None = None # Only for Kickbase's own listings
    ### Managers who may still buy a player of this club (at most three per club), the richest first.
    ### With `rivals_by_budget` the ones who cannot afford the price are left out as well.
    rivals: list[RivalOut] = []
    rivals_by_budget: bool = False
    own_club_players: int = 0
    own_club_full: bool = False
    ### Forecast market value change until the next lineup deadline, minus what the price is above the value
    margin_to_matchday: int | None = None
    updates_to_matchday: int = 0
    ### Recommended bid: from the league's usual markup up to beating the likely bidders
    bid_low: int | None = None
    bid_high: int | None = None
    ### Forecast gain until the deadline minus what the bid is above the market value
    margin_low: int | None = None
    margin_high: int | None = None
    expected_points: float | None = None # Next matchday
    play_probability: float | None = None
    next_opponent_id: str | None = None
    next_home: bool | None = None
    odds: list[float | None] | None = None # Home, draw, away of his next match
    seller_in_minus: bool = False # The selling manager is estimated below zero
    bidders_learned: bool = False # The bidder chances come from the logged auctions


class LostAuctionOut(Schema):
    player_id: str
    player_name: str | None = None
    date: datetime
    own_bid: int
    price: int # What the winner paid
    winner_id: str
    winner: str


class BalancePointOut(Schema):
    date: datetime
    balance: int


class RivalProfileOut(Schema):
    id: str
    name: str
    image: str | None = None
    is_self: bool = False
    squad_size: int
    fit_positions: dict[int, int] # Fit players per position
    needs: list[int] # Positions he is short of
    unavailable: list[str] # Injured or suspended players of his squad
    blocked_clubs: list[str] # Clubs he owns three players of
    purchases: int # From Kickbase this season
    purchases_recent: int # All purchases of the last 14 days
    overpay_median: float | None = None
    overpay_by_class: list[float | None] = [] # Median share per price class
    active_hours: list[int] = [] # Local hours he buys at most
    last_activity: datetime | None = None
    estimated_balance: int | None = None
    max_bid: int | None = None
    in_minus: bool = False
    balance_history: list[BalancePointOut] = []
    lost_to: list[LostAuctionOut] = [] # The viewer's auctions he won


class RivalsOut(Schema):
    league_overpay_by_class: list[float | None]
    price_classes: list[int] # Upper bounds of the price classes, the last one is open
    deadline: datetime | None = None
    managers: list[RivalProfileOut]
    lost: list[LostAuctionOut] = []


class WatchedPlayerOut(PlayerOut):
    expires_at: datetime | None = None # End of the market listing, if there is one


class WatchOut(Schema):
    watched: bool


class FairPlayerOut(PlayerOut):
    games: int
    fair_value: int
    gap: float # Market value against the fair value, -0.3 means 30% below it
    rating: FairRating


class FairCurvePointOut(Schema):
    points: int
    value: int


class FairValuesOut(Schema):
    min_games: int # Players need this many games to get a fair value
    band: float # A smaller gap counts as fair
    typical_gap: float | None = None
    players: list[FairPlayerOut] = []
    curves: dict[int, list[FairCurvePointOut]] = {} # By position


class TransferOut(Schema):
    id: str
    date: datetime
    player_id: str
    player_name: str | None = None
    team_id: str | None = None
    buyer: str | None = None
    buyer_id: str | None = None
    seller: str | None = None
    seller_id: str | None = None
    price: int


class PlayerDetailOut(PlayerOut):
    ### `[date, value]` pairs, oldest first
    history: list[tuple[str, int]] = []
    transfers: list[TransferOut] = []


class ManagerOut(Schema):
    id: str
    name: str
    image: str | None = None
    is_self: bool = False
    placement: int | None = None
    points: int | None = None
    points_behind: int | None = None
    average_points: int | None = None
    team_value: int | None = None
    matchday_wins: int | None = None
    budget: int | None = None # The real budget, only known for the logged in user
    estimated_balance: int | None = None
    max_bid: int | None = None
    squad_size: int = 0
    transfers: int = 0
    bought: int = 0
    sold: int = 0
    transfer_profit: int | None = None


class BattleEntryOut(Schema):
    manager_id: str
    name: str
    image: str | None = None
    placement: int | None = None
    value: float | None = None


class BattleOut(Schema):
    type: int
    name: str
    description: str = ""
    entries: list[BattleEntryOut] = []


class TurnoverOut(Schema):
    manager: str
    manager_id: str | None = None
    player_id: str
    player_name: str | None = None
    first_name: str | None = None
    image: str | None = None
    team_id: str | None = None
    position: int | None = None
    buy_price: int | None = None
    buy_date: datetime | None = None
    bought_from: str | None = None
    starter: bool = False
    sell_price: int
    sell_date: datetime
    sold_to: str | None = None
    profit: int | None = None
    days_held: int | None = None


class OverpayStatsOut(Schema):
    purchases: int
    median: float # Paid on top of the market value
    average: float
    total: int
    average_amount: int # per purchase
    highest: float


class OverpayManagerOut(OverpayStatsOut):
    manager: str
    manager_id: str | None = None


class OverpayPurchaseOut(Schema):
    id: str
    date: datetime
    manager: str
    manager_id: str | None = None
    player_id: str
    player_name: str | None = None
    first_name: str | None = None
    image: str | None = None
    team_id: str | None = None
    position: int | None = None
    price: int
    market_value: int
    overpay: int
    overpay_share: float


class OverpayOut(Schema):
    league: OverpayStatsOut | None = None # None until the first purchase
    managers: list[OverpayManagerOut] = []
    purchases: list[OverpayPurchaseOut] = []


class ChartManager(Schema):
    id: str
    name: str


class ChartOut(Schema):
    managers: list[ChartManager]
    ### One object per x value, e.g. `{"date": "2026-08-01", "<managerId>": 1200000}`
    rows: list[dict]


class MatchdayChartsOut(Schema):
    managers: list[ChartManager]
    team_values: list[dict]
    points: list[dict]
    placements: list[dict]


class MatchOut(Schema):
    id: str
    day: int
    kickoff: datetime | None = None
    team1_id: str | None = None
    team2_id: str | None = None
    team1_goals: int | None = None
    team2_goals: int | None = None
    status: int | None = None
    minute: str | None = None

    @computed_field
    @property
    def state(self) -> MatchState:
        return analytics.match_state(self.status, self.minute)


class FixturesOut(Schema):
    day: int | None
    current_day: int | None
    number_of_days: int | None
    matches: list[MatchOut]


class LiveEventOut(Schema):
    name: str
    count: int
    points: int


class LiveTimelineEventOut(Schema):
    """One scoring event of a player, as it happened"""
    name: str
    points: int
    minute: int | None = None
    ### Goals, assists and cards, for an icon. None for everything else
    kind: analytics.EventKind | None = None


class LivePlayerOut(Schema):
    id: str
    first_name: str | None = None
    last_name: str
    image: str | None = None
    team_id: str | None = None
    position: int = 0
    points: int = 0
    match_status: int | None = None
    match_state: MatchState = "upcoming"
    match_minute: str | None = None
    minute: int | None = None # Minutes played, known once the match is finished
    role: PlayerRole | None = None
    on_field: bool = False
    goals: int = 0
    assists: int = 0
    own_goals: int = 0
    yellow_cards: int = 0
    yellow_red_cards: int = 0
    red_cards: int = 0
    ### The events summed up per type, the biggest first
    events: list[LiveEventOut] = []
    ### Every single event in the order of the match
    timeline: list[LiveTimelineEventOut] = []


class LiveManagerOut(Schema):
    id: str
    name: str
    image: str | None = None
    is_self: bool = False
    matchday_points: int = 0
    season_points: int | None = None
    placement: int | None = None
    players_started: int = 0
    players_on_field: int = 0
    lineup_size: int = 0
    players: list[LivePlayerOut] = []


class LiveOut(Schema):
    day: int | None
    updated_at: datetime # When Kickbase was asked, the answer is reused for cache_seconds
    cache_seconds: int
    ### A real match is on. Only then Kickbase is asked again without an explicit refresh
    match_running: bool = False
    matches: list[MatchOut]
    managers: list[LiveManagerOut]
    ### Asked from Kickbase in this round, only players whose match runs or just ended
    fetched_players: int = 0
    ### Kickbase did not answer for them, their last known points are shown
    stale_players: int = 0
    ### Kickbase did not answer and nothing is known yet: the manager's total comes from the ranking
    missing_players: int = 0


class PlayerMatchOut(Schema):
    day: int | None = None
    kickoff: datetime | None = None
    opponent_id: str | None = None
    home: bool = True
    goals: int | None = None # Of the player's club
    opponent_goals: int | None = None
    points: int | None = None # None when the player did not play or the match is still to come
    minutes: int | None = None
    role: PlayerRole | None = None
    state: MatchState = "upcoming"
    current: bool = False # The current matchday


class PlayerMatchesOut(Schema):
    season: str | None = None
    matches: list[PlayerMatchOut] = []


class BidIn(Schema):
    price: int = Field(gt=0)


class BidOut(Schema):
    own_bid: int | None = None


class LineupsOut(Schema):
    day: int | None
    lineups: dict[str, list[str]] # Manager id -> the player ids of their current starting eleven


### ===============================================================================
### Manager tools
### ===============================================================================

class ExpectationOut(Schema):
    player_id: str
    expected: float
    form: float | None = None
    season_average: float | None = None
    availability: float
    opponent_factor: float
    opponent_id: str | None = None
    home: bool | None = None
    play_probability: float | None = None # Share of the last five matches he played
    win_probability: float | None = None # Of his club, from the betting odds
    reasons: list[str] = []


class MatchdayOut(Schema):
    day: int
    first_kickoff: datetime
    deadline: datetime


class SquadPlayerOut(Schema):
    id: str
    first_name: str | None = None
    last_name: str
    team_id: str | None = None
    image: str | None = None
    position: int
    status: int
    status_text: str | None = None
    market_value: int
    average_points: int | None = None
    purchase_price: int | None = None
    expected: ExpectationOut
    in_lineup: bool = False # Saved at Kickbase
    in_best: bool = False # Part of the best eleven
    forecast: int | None = None


class RescueOut(Schema):
    sales: list[str]
    budget_after: int
    expected_before: float
    expected_after: float
    expected_loss: float
    enough: bool


class SellAdviceOut(Schema):
    player_id: str
    reason: str
    expected_drop: int # Forecast value change until the deadline
    in_best: bool


class LeagueForecastOut(Schema):
    manager_id: str
    name: str
    image: str | None = None
    is_self: bool = False
    expected: float # Expected points of the saved eleven
    fielded: int
    unavailable: int # Fielded players who will not play


class CheckOut(Schema):
    level: str # ok, warn or error
    message: str


class CoachOut(Schema):
    """Everything about the viewer's next matchday in one answer."""
    matchday: MatchdayOut | None = None
    live_day: int | None = None
    lineup_open: bool = False
    budget: int | None = None
    squad: list[SquadPlayerOut] = []
    saved_formation: str | None = None
    saved_lineup: list[str] = []
    saved_expected: float = 0
    best_formation: str
    best_lineup: list[str] = []
    best_expected: float = 0
    rescue: RescueOut | None = None
    checks: list[CheckOut] = []
    lineup_source: str = "kickbase" # Where saved_lineup comes from
    sell_advice: list[SellAdviceOut] = []
    league_forecast: list[LeagueForecastOut] = []
    updates_to_matchday: int = 0
    sell_ratio: float | None = None # What Kickbase paid for instant sales against the market value


class LineupApplyOut(Schema):
    formation: str
    player_ids: list[str]
    confirmed: bool # Kickbase reports the new lineup afterwards
    response: str | None = None # What Kickbase answered, for checking the undocumented request


class SellOut(Schema):
    player_id: str
    budget: int | None = None
    response: str | None = None


class TraderOptionsIn(Schema):
    """The autotrader's thresholds, see core.trader.Options. The bounds match its OPTION_LIMITS."""
    min_gain: float = Field(2.0, ge=0, le=100, allow_inf_nan=False) # Expected points the eleven gains at least
    max_cost_per_point: int = Field(300_000, ge=0, le=50_000_000) # € above the replaced player per point
    min_avg_edge: int = Field(10, ge=0, le=200) # % better season average than the replaced player
    min_play: int = Field(60, ge=0, le=100) # % of the club's last five matches
    lineup_share: int = Field(100, ge=10, le=100) # % of the free budget per lineup bid
    profit_share: int = Field(60, ge=10, le=100) # % of team value plus balance all profit trades together
    reserve: int = Field(0, ge=0, le=500_000_000) # € never spent
    cover_max_price: int = Field(3_000_000, ge=0, le=50_000_000)
    daily_bids: int = Field(6, ge=0, le=30)
    daily_sales: int = Field(3, ge=0, le=30)
    stop_loss: int = Field(3_000_000, ge=0, le=100_000_000) # Weekly loss that pauses profit trading, 0 never
    sell_window: int = Field(20, ge=5, le=180) # Minutes before the auction ends
    starter_lock: int = Field(60, ge=0, le=1440) # Minutes before the first kick-off
    min_roi: float = Field(2.0, ge=0, le=100, allow_inf_nan=False) # % net return of a profit buy
    credit_mode: int = Field(1, ge=0, le=2) # 0 no credit, 1 eleven and substitutes, 2 also profit trades
    trailing_stop: int = Field(5, ge=0, le=50) # % below the peak since the purchase, 0 off
    position_stop: int = Field(10, ge=0, le=100) # % net loss on the purchase price, 0 off
    max_hold_days: int = Field(7, ge=0, le=60) # Days without enough left to gain, 0 off
    shadow: bool = True
    rescue_override: bool = False # Rescue sales may sell locked players


class AutomationSettingsIn(Schema):
    auto_scout: bool = False
    scout_threshold: int = Field(250_000, ge=0, le=50_000_000)
    scout_limit: int = Field(30, ge=1, le=100)
    auto_lineup: bool = False
    deadline_alerts: bool = True
    listing_alerts: bool = True
    sell_alerts: bool = True
    trader: bool = False
    trader_live: bool = False
    trader_profit: bool = True
    trader_options: TraderOptionsIn = Field(default_factory=lambda: TraderOptionsIn())


class TraderImportIn(BaseModel):
    """Plain snake_case keys, as in the export. Values are clamped to their limits."""
    options: dict | None = None
    learned: dict | None = None


class TraderImportOut(BaseModel):
    options: dict
    learned: dict
    ignored: list[str] = [] # Keys that do not exist


class AutomationSettingsOut(AutomationSettingsIn):
    session_expires_at: datetime | None = None # Automation works until then, without the env account
    uses_service_account: bool = False
    trader_on_server: bool = True # KBI_AUTOMATION__TRADER


class TraderWeekOut(Schema):
    week: str # ISO week, e.g. 2026-W48
    planned: int = 0 # Dry run
    bids: int = 0
    won: int = 0
    lost: int = 0
    sales: int = 0
    spent: int = 0
    received: int = 0
    profit: int = 0 # Realized: sale minus purchase
    points_gain: float = 0 # Expected points the lineup purchases added
    shadow_trades: int = 0 # Paper purchases finished this week
    shadow_profit: int = 0 # ... and what they would have made


class TradeOut(Schema):
    id: int
    at: datetime
    player_id: str
    name: str | None = None
    kind: str # bid or sell
    purpose: str
    status: str
    price: int
    market_value: int
    paid: int | None = None
    profit: int | None = None
    points_gain: float = 0
    reason: str | None = None


class ShadowOut(Schema):
    id: int
    at: datetime
    player_id: str
    name: str | None = None
    kind: str # buy or sell
    purpose: str
    status: str # watching, holding, lost, expired, done
    bid: int = 0
    market_value: int
    winner_price: int | None = None
    value_after: int | None = None
    result: int | None = None # buy: profit on paper; sell: value change after the sale


class ShadowSummaryOut(Schema):
    open: int = 0
    done: int = 0
    profit: int = 0
    hit_rate: float | None = None # Share of finished paper purchases with a profit
    sold_then_rose: float | None = None # Share of sold players who rose by 100k+ afterwards


class TraderLearnedOut(Schema):
    extra: list[float] # Per price class: where between the usual and the safe bid it bids (0..1)
    min_margin: int # Forecast gain a profit purchase needs at least
    won: int
    lost: int
    shadow_won: int = 0
    shadow_lost: int = 0
    gain_scale: float = 1.0 # How much of a forecast gain is trusted
    gain_samples: int = 0
    swap_edge: int = 100_000 # How much more per day a swap target has to rise
    regret_samples: int = 0


class TraderOut(Schema):
    weeks: list[TraderWeekOut] = []
    trades: list[TradeOut] = []
    shadows: list[ShadowOut] = []
    shadow_summary: ShadowSummaryOut = Field(default_factory=lambda: ShadowSummaryOut())
    learned: TraderLearnedOut
    paused: bool = False # Profit trading paused after a weekly loss
    pause_reason: str | None = None # Live trading paused automatically, e.g. after repeated API errors
    enabled_on_server: bool = True


class AutomationEventOut(Schema):
    id: int
    at: datetime
    kind: str
    ok: bool
    message: str
    details: dict = {}


class ScoutRunOut(Schema):
    added: list[str] = []
    removed: list[str] = []
    flagged: list[str] = [] # Every player at or above the threshold right now


class ForecastQualityOut(Schema):
    weights: list[float]
    features: list[str]
    learned: bool
    training_rows: int
    error: float | None = None
    naive_error: float | None = None
    checked: int = 0 # Forecasts compared with the real update
    direction_hits: float | None = None # Share with the right direction
    mean_abs_error: int | None = None
    flag_precision: float | None = None # Of the players forecast at >= 250k, share that really rose >= 250k


class PushKeyOut(Schema):
    public_key: str | None = None # None when push is not configured
    subscribed: int = 0


class PushSubscriptionIn(Schema):
    endpoint: str = Field(min_length=10, max_length=2000)
    p256dh: str = Field(min_length=10, max_length=500)
    auth: str = Field(min_length=4, max_length=200)


class BuyOptionOut(Schema):
    player: MarketPlayerOut
    bid: int
    margin: int | None = None
    points_gain: float = 0 # More expected points of the best eleven with him
    blocked: str | None = None


### ===============================================================================
### Manager detail
### ===============================================================================

class ManagerSquadPlayerOut(PlayerOut):
    in_lineup: bool = False
    form: list[tuple[int, int | None]] = [] # (matchday, points) of the club's last five matches, oldest first
    starts: int | None = None # Starting eleven in the club's last ten matches
    day_points: int | None = None # Points on the selected matchday


class ValueSplitOut(Schema):
    team_value: int
    today: int # Market value change of today


class AchievementOut(Schema):
    key: str
    group: str
    name: str
    description: str
    reward: int
    kind: str
    count: int | None = None
    amount: int


class SeasonPointOut(Schema):
    day: int
    points: int | None = None
    season_points: int | None = None
    placement: int | None = None


class ManagerDetailOut(Schema):
    id: str
    name: str
    image: str | None = None
    is_self: bool = False
    placement: int | None = None
    points: int | None = None
    previous_id: str | None = None
    next_id: str | None = None
    transfers: int = 0
    squad_size: int = 0
    max_squad: int = 18
    total: ValueSplitOut
    lineup: ValueSplitOut
    bench: ValueSplitOut
    transfer_profit: int = 0
    overpay_average: float | None = None
    clubs: list[tuple[str, int]] = [] # (team id, players), most first
    positions: dict[int, int] = {}
    estimated_balance: int | None = None
    max_bid: int | None = None
    lineup_day: int | None = None # The matchday the lineup is from, None for the current one
    lineup_ids: list[str] = []
    days: list[int] = [] # Matchdays with a stored lineup
    squad: list[ManagerSquadPlayerOut] = []
    turnovers: list[TurnoverOut] = []
    transfer_list: list[TransferOut] = []
    achievements: list[AchievementOut] = []
    achievements_total: int = 0
    season: list[SeasonPointOut] = []
    team_values: list[tuple[str, int]] = [] # (date, value) every evening
    matchday_dates: list[tuple[int, str]] = [] # (matchday, date of its first kick-off)


class BalanceCorrectionOut(Schema):
    amount: int # Added to every estimated balance
    members: int # Members whose real budget it was learned from
    residuals: list[int] = []


class AchievementCheckOut(Schema):
    key: str
    name: str
    kickbase: int | None = None # Kickbase's counter (all seasons of the league)
    app: int | None = None # What the app counts for this season


class LearningOut(Schema):
    expectation: dict = {}
    expectation_logged: int = 0
    expectation_checked: int = 0
    bidder: dict = {}
    auctions_logged: int = 0
    auctions_resolved: int = 0
    achievement_mode: dict = {}
    sell_ratio: dict = {}
    balance_correction: BalanceCorrectionOut | None = None
    achievements: list[AchievementCheckOut] = []
    achievements_checked_at: datetime | None = None
