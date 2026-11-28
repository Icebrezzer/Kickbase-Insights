"""Offline shadow settlement. All inputs come from the current round or local storage."""

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import tuple_
from sqlmodel import Session, select

from core import analytics
from core.shadow_intelligence import AuctionEvidence, bid_variants, sale_strategies, settle_bids
from db.models import (
    DecisionSnapshot,
    ForecastObservation,
    MarketValueHistory,
    ShadowAnalysis,
    TradeLog,
    Transfer,
)


def freeze(user, league, pid, auction, values, listing, extra, deadline, trailing, now):
    end = values.get("expires_at")
    if end is None and listing and listing.expires_in is not None:
        end = now + timedelta(seconds=listing.expires_in)
    floor = values.get("min_bid") or max(values.get("price") or 0, values.get("value") or 0)
    bids = bid_variants(floor, values.get("hypothetical_bid"), None) if floor > 0 else {}
    if end and end <= now:
        bids = {}
    if bids and extra.get("ev") and extra["ev"] >= bids.get("minimum", 0):
        bids["ev"] = extra["ev"]
    return ShadowAnalysis(user_id=user, league_id=league, player_id=pid, auction=auction,
        next_check=end + timedelta(seconds=2) if end else None, inputs={
            "bids": bids, "end": end.isoformat() if end else None, "seller": listing.seller.id if listing and listing.seller else None,
            "listed": bool(listing and listing.listed_at), "cap": extra.get("cap"),
            "ratio": values.get("sell_ratio"), "deadline": deadline, "trailing": trailing,
            "no_buyer": bool(listing and listing.seller is None and listing.expires_in == 0 and listing.offer_count == 0),
        })


def record_closed_listings(session, user, league, listings):
    """A later observation of the same expired free-agent listing can supply no-buyer evidence."""
    closed = [(p.id, p.listed_at.isoformat()) for p in listings.values()
              if p.listed_at and p.seller is None and p.expires_in == 0 and p.offer_count == 0]
    if closed:
        for row in session.exec(select(ShadowAnalysis).where(ShadowAnalysis.user_id == user,
                ShadowAnalysis.league_id == league, tuple_(ShadowAnalysis.player_id, ShadowAnalysis.auction).in_(closed))):
            if not row.inputs.get("no_buyer"):
                row.inputs = {**row.inputs, "no_buyer": True}


def settle_due(session: Session, user: str, league: str, now: datetime):
    rows = session.exec(select(ShadowAnalysis).where(ShadowAnalysis.user_id == user,
        ShadowAnalysis.league_id == league, ShadowAnalysis.next_check <= now)
        .order_by(ShadowAnalysis.next_check, ShadowAnalysis.player_id, ShadowAnalysis.auction).limit(64)).all()
    if not rows:
        return
    ends = [datetime.fromisoformat(row.inputs["end"]) for row in rows]
    jitter = timedelta(seconds=1)
    transfers = defaultdict(list)
    for sale in session.exec(select(Transfer).where(Transfer.league_id == league,
            Transfer.player_id.in_({r.player_id for r in rows}), Transfer.date >= min(ends) - jitter,
            Transfer.date <= max(ends) + jitter)):
        transfers[sale.player_id].append(sale)
    ids = {r.player_id for r in rows}
    overlaps = defaultdict(list)
    snap = DecisionSnapshot
    for pid, auction, listed, expires in session.exec(select(snap.player_id, snap.auction, snap.listed_at, snap.expires_at)
            .where(snap.user_id == user, snap.league_id == league, snap.player_id.in_(ids),
                   snap.listed_at <= max(ends) + jitter, snap.expires_at >= min(ends) - jitter)):
        overlaps[pid].append((auction, listed, expires))
    histories = dict(session.exec(select(MarketValueHistory.player_id, MarketValueHistory.points)
                                  .where(MarketValueHistory.player_id.in_(ids))).all())
    lost_bids = defaultdict(list)
    for bid in session.exec(select(TradeLog).where(TradeLog.user_id == user, TradeLog.league_id == league,
            TradeLog.player_id.in_(ids), TradeLog.kind == "bid", TradeLog.status == "lost",
            TradeLog.resolved_at >= min(ends) - jitter, TradeLog.at <= max(ends) + jitter)):
        lost_bids[bid.player_id].append(bid)
    observations = defaultdict(dict)
    for obs in session.exec(select(ForecastObservation).where(ForecastObservation.league_id == league,
            ForecastObservation.player_id.in_(ids), ForecastObservation.day >= analytics.market_value_day(min(ends)),
            ForecastObservation.day <= analytics.market_value_day(max(ends)) + 14, ForecastObservation.observed_at <= now)):
        observations[obs.player_id][obs.day] = obs
    for row, end in zip(rows, ends, strict=True):
        data = row.inputs
        matches = [s for s in transfers[row.player_id] if abs(s.date - end) <= jitter]
        conflict = any(other != row.auction and listed - jitter <= end <= expires + jitter
                       for other, listed, expires in overlaps[row.player_id])
        sale = matches[0] if len(matches) == 1 and data["listed"] and not conflict else None
        if sale and (not sale.buyer_id or sale.seller_id != data["seller"] or
                     (sale.seller and not sale.seller_id) or sale.price <= 0):
            sale = None
        own = sale is not None and sale.buyer_id == user
        evidence = AuctionEvidence(sale.price if sale and not own else None, bool(not conflict and not matches and data["no_buyer"]))
        row.result = {"outcomes": {v.name: v.outcome for v in settle_bids(data["bids"], evidence)},
                      "winner_price": sale.price if sale else None, "own": own, "no_buyer": evidence.confirmed_no_buyer}
        row.next_check = None if sale or evidence.confirmed_no_buyer or now >= end + timedelta(days=2) else now + timedelta(hours=1)
        if sale and not own:
            listed_at = datetime.fromisoformat(row.auction)
            lost = [b for b in lost_bids[row.player_id] if listed_at <= b.at <= sale.date
                    and b.details.get("winner_id") == sale.buyer_id and b.details.get("winner_price") == sale.price]
            if len(lost) == 1:
                row.result = {**row.result, "real_lost": True}
        if sale and (own or "won" in row.result["outcomes"].values()):
            start = analytics.market_value_day(sale.date)
            today = analytics.market_value_day(now)
            points = {d: (v, None) for d, v in histories.get(row.player_id, []) if start <= d <= min(start + 14, today)}
            deadline = datetime.fromisoformat(data["deadline"]) if data.get("deadline") else None
            for day, obs in observations[row.player_id].items():
                if day <= today:
                    points[day] = (obs.value, obs.forecast_1)
            end_day = analytics.market_value_day(deadline) if deadline and sale.date < deadline <= now else None
            row.result = {**row.result, **sale_strategies(start, points, data["ratio"] or 0, data["trailing"], end_day)}
            if today <= start + 14:
                row.next_check = now + timedelta(hours=6)
    finished = [(row.player_id, row.auction) for row in rows if row.next_check is None]
    if finished:
        from sqlalchemy import update
        session.exec(update(DecisionSnapshot).where(DecisionSnapshot.user_id == user, DecisionSnapshot.league_id == league,
            tuple_(DecisionSnapshot.player_id, DecisionSnapshot.auction).in_(finished)).values(resolved=True))
