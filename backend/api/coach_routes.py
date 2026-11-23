"""REST API of the manager tools: matchday, best eleven, instant sales, automation and push."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException

from api.routes import (
    LeagueDep,
    LeagueIdDep,
    PlayerIdPath,
    StateDep,
    ViewerDep,
    ask_kickbase,
    forget_private,
)
from api.schemas import (
    AutomationEventOut,
    AutomationSettingsIn,
    AutomationSettingsOut,
    CoachOut,
    ForecastQualityOut,
    LineupApplyOut,
    PushKeyOut,
    PushSubscriptionIn,
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
