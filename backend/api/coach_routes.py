"""REST API of the manager tools: matchday, best eleven, instant sales, automation and push."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query
from sqlmodel import Session

from api.routes import (
    LeagueDep,
    LeagueIdDep,
    PlayerIdPath,
    SessionDep,
    StateDep,
    ViewerDep,
    ask_kickbase,
    cached,
    forget_private,
    insights,
    shows_balances,
)
from api.schemas import (
    AutomationEventOut,
    AutomationSettingsIn,
    AutomationSettingsOut,
    BuyOptionOut,
    CoachOut,
    ForecastQualityOut,
    LearningOut,
    LineupApplyOut,
    ManagerDetailOut,
    PushKeyOut,
    PushSubscriptionIn,
    RivalsOut,
    ScoutRunOut,
    SellOut,
)
from db.models import utcnow
from kickbase import KickbaseClient

router = APIRouter(prefix="/api")

### A manual scouting run at most this often per user
SCOUT_COOLDOWN = timedelta(minutes=2)
_last_scout: dict[tuple[str, str], datetime] = {}


def _automation(state):
    if state.automation is None:
        raise HTTPException(503, "Die Automatik ist nicht gestartet.")
    return state.automation


@router.get("/coach", response_model=CoachOut)
async def coach(state: StateDep, league: LeagueDep, viewer: ViewerDep) -> CoachOut:
    """The viewer's next matchday: deadline, checks, expected points, best eleven, budget rescue."""
    automation = _automation(state)
    return await ask_kickbase(state, viewer, lambda client: automation.coach_view(league, viewer.user_id, client))


@router.post("/coach/lineup", response_model=LineupApplyOut)
async def apply_lineup(state: StateDep, league: LeagueDep, viewer: ViewerDep) -> LineupApplyOut:
    """Saves the best eleven at Kickbase."""
    automation = _automation(state)
    result = await ask_kickbase(
        state, viewer, lambda client: automation.apply_lineup(league, viewer.user_id, client)
    )
    state.live._lineups.pop(league.id, None)
    return result


@router.post("/squad/{player_id}/sell", response_model=SellOut)
async def sell(
    state: StateDep, league: LeagueDep, league_id: LeagueIdDep, viewer: ViewerDep, player_id: PlayerIdPath
) -> SellOut:
    """Sells one of the viewer's players to Kickbase right away. Cannot be undone."""
    automation = _automation(state)

    async def call(client: KickbaseClient) -> SellOut:
        result = await automation.sell(league, viewer.user_id, client, player_id)
        await state.sync.refresh_personal(league_id, client)
        ### The squads of the league changed, a sync brings the stored data up to date
        state.spawn(state.sync.run(league_id, client, "manual", viewer.name))
        return result

    result = await ask_kickbase(state, viewer, call)
    forget_private(state, league_id, viewer)
    return result


@router.get("/rivals", response_model=RivalsOut)
def rivals(state: StateDep, session: SessionDep, league: LeagueDep, viewer: ViewerDep) -> RivalsOut:
    """Every manager as a bidder: habits, needs, weaknesses, money and the auctions he won against you."""
    allowed = shows_balances(state.settings, viewer)
    return cached(state, league, ("rivals",), lambda: insights(state, session, league, viewer).rival_profiles(allowed), viewer)


@router.get("/managers/{manager_id}/detail", response_model=ManagerDetailOut)
async def manager_detail(
    state: StateDep,
    league: LeagueDep,
    viewer: ViewerDep,
    manager_id: Annotated[str, Path(pattern=r"^\d+$")],
    day: Annotated[int | None, Query(ge=1, le=60)] = None,
) -> ManagerDetailOut:
    """Everything about one manager: squad, lineup, values, clubs, transfers, achievements, season."""
    current: list[str] | None = None
    if day is None:
        try:
            lineups = await ask_kickbase(state, viewer, lambda client: state.live.lineups(league, client))
            current = lineups.lineups.get(manager_id)
        except HTTPException:
            current = None
    allowed = shows_balances(state.settings, viewer)

    def build() -> ManagerDetailOut | None:
        with Session(state.engine) as session:
            return insights(state, session, league, viewer).manager_detail(manager_id, allowed, current, day)

    result = await asyncio.to_thread(build)
    if result is None:
        raise HTTPException(404, "Diesen Manager gibt es in der Liga nicht.")
    return result


@router.get("/planner/buys", response_model=list[BuyOptionOut])
def buy_planner(state: StateDep, session: SessionDep, league: LeagueDep, viewer: ViewerDep) -> list[BuyOptionOut]:
    """Market players worth buying now, by value gain until the deadline and expected points."""
    return cached(state, league, ("buys",), lambda: insights(state, session, league, viewer).buy_options(), viewer)


@router.get("/learning", response_model=LearningOut)
async def learning_status(state: StateDep, league: LeagueDep, viewer: ViewerDep) -> LearningOut:
    """What the app learned: expected points weights, bidder model, achievement counting, sell ratio,
    balance correction, and the viewer's achievements next to Kickbase's own counters."""
    automation = _automation(state)

    def build() -> LearningOut:
        status = automation.learning.status(league)
        with Session(state.engine) as session:
            return insights(state, session, league, viewer).learning_view(status)

    return await asyncio.to_thread(build)


@router.get("/odds/sample")
async def odds_sample(state: StateDep, viewer: ViewerDep) -> list[dict]:
    """The latest stored answers of the odds sources, to check Kickbase's undocumented bet link."""
    automation = _automation(state)
    if automation.odds is None:
        return []
    return await asyncio.to_thread(automation.odds.sample)


### ===============================================================================
### Automation settings
### ===============================================================================

def _settings_out(state, viewer, row) -> AutomationSettingsOut:
    automation = state.automation
    return AutomationSettingsOut(
        auto_scout=row.auto_scout,
        scout_threshold=row.scout_threshold,
        scout_limit=row.scout_limit,
        auto_lineup=row.auto_lineup,
        deadline_alerts=row.deadline_alerts,
        listing_alerts=row.listing_alerts,
        sell_alerts=row.sell_alerts,
        session_expires_at=automation.session_expiry(viewer.user_id),
        uses_service_account=automation.accounts.service_user_id == viewer.user_id,
    )


@router.get("/automation/settings", response_model=AutomationSettingsOut)
async def get_automation(state: StateDep, league_id: LeagueIdDep, viewer: ViewerDep) -> AutomationSettingsOut:
    automation = _automation(state)
    row = await asyncio.to_thread(automation.get_settings, viewer.user_id, league_id)
    return await asyncio.to_thread(_settings_out, state, viewer, row)


@router.put("/automation/settings", response_model=AutomationSettingsOut)
async def put_automation(
    state: StateDep, league_id: LeagueIdDep, viewer: ViewerDep, body: AutomationSettingsIn
) -> AutomationSettingsOut:
    automation = _automation(state)
    row = await asyncio.to_thread(automation.get_settings, viewer.user_id, league_id)
    for name, value in body.model_dump().items():
        setattr(row, name, value)
    row = await asyncio.to_thread(automation.save_settings, row)
    return await asyncio.to_thread(_settings_out, state, viewer, row)


@router.get("/automation/events", response_model=list[AutomationEventOut])
async def automation_events(state: StateDep, league_id: LeagueIdDep, viewer: ViewerDep):
    automation = _automation(state)
    return await asyncio.to_thread(automation.events, viewer.user_id, league_id)


@router.post("/automation/scout", response_model=ScoutRunOut)
async def run_scouting(state: StateDep, league: LeagueDep, viewer: ViewerDep) -> ScoutRunOut:
    """Compares the scouting list with the forecasts now, e.g. when the market page opens."""
    automation = _automation(state)
    setting = await asyncio.to_thread(automation.get_settings, viewer.user_id, league.id)
    if not setting.auto_scout:
        return ScoutRunOut()
    key = (viewer.user_id, league.id)
    last = _last_scout.get(key)
    now = utcnow()
    if last is not None and now - last < SCOUT_COOLDOWN:
        return ScoutRunOut()
    _last_scout[key] = now
    return await ask_kickbase(
        state, viewer, lambda client: automation.reconcile_scouting(league, viewer.user_id, client)
    )


@router.get("/automation/forecast", response_model=ForecastQualityOut)
async def forecast_quality(state: StateDep, league_id: LeagueIdDep, viewer: ViewerDep) -> ForecastQualityOut:
    automation = _automation(state)
    setting = await asyncio.to_thread(automation.get_settings, viewer.user_id, league_id)
    return await asyncio.to_thread(automation.forecast_quality, setting.scout_threshold)


### ===============================================================================
### Push messages
### ===============================================================================

@router.get("/push/key", response_model=PushKeyOut)
async def push_key(state: StateDep, viewer: ViewerDep) -> PushKeyOut:
    push = state.push
    if push is None or not push.enabled:
        return PushKeyOut()
    return PushKeyOut(public_key=push.public_key, subscribed=await asyncio.to_thread(push.count, viewer.user_id))


@router.post("/push/subscribe", response_model=PushKeyOut)
async def push_subscribe(state: StateDep, viewer: ViewerDep, body: PushSubscriptionIn) -> PushKeyOut:
    push = state.push
    if push is None or not push.enabled:
        raise HTTPException(503, "Push ist auf dem Server nicht eingerichtet (KBI_PUSH__SUBJECT).")
    await asyncio.to_thread(push.subscribe, viewer.user_id, body.endpoint, body.p256dh, body.auth)
    return PushKeyOut(public_key=push.public_key, subscribed=await asyncio.to_thread(push.count, viewer.user_id))


@router.post("/push/unsubscribe", response_model=PushKeyOut)
async def push_unsubscribe(state: StateDep, viewer: ViewerDep, body: PushSubscriptionIn) -> PushKeyOut:
    push = state.push
    if push is None or not push.enabled:
        return PushKeyOut()
    await asyncio.to_thread(push.unsubscribe, viewer.user_id, body.endpoint)
    return PushKeyOut(public_key=push.public_key, subscribed=await asyncio.to_thread(push.count, viewer.user_id))


@router.post("/push/test", response_model=PushKeyOut)
async def push_test(state: StateDep, viewer: ViewerDep) -> PushKeyOut:
    push = state.push
    if push is None or not push.enabled:
        raise HTTPException(503, "Push ist auf dem Server nicht eingerichtet (KBI_PUSH__SUBJECT).")
    delivered = await push.send(viewer.user_id, "Kickbase Insights", "Push funktioniert. ⚽", "/spieltag")
    if delivered == 0:
        raise HTTPException(400, "Keine Nachricht zugestellt. Ist die App auf dem Homebildschirm und Push erlaubt?")
    return PushKeyOut(public_key=push.public_key, subscribed=await asyncio.to_thread(push.count, viewer.user_id))
