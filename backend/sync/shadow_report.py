"""Read-only comparison of independent auction counterfactuals, scoped to the viewer."""

from collections import Counter, defaultdict
from datetime import timedelta
from statistics import median

from sqlalchemy import and_
from sqlmodel import Session, select

from core.shadow_intelligence import classify, weighted_win_rate
from db.models import DecisionSnapshot, ShadowAnalysis, TradeLog, utcnow


def shadow_report(engine, user, league):
    now = utcnow()
    since = now - timedelta(days=30)
    snap, analysis = DecisionSnapshot, ShadowAnalysis
    groups = defaultdict(list)
    variants = defaultdict(Counter)
    exits = defaultdict(list)
    finance_counts = Counter()
    categories = Counter()
    learning = []
    with Session(engine) as session:
        join = and_(*(getattr(snap, k) == getattr(analysis, k) for k in ("user_id", "league_id", "player_id", "auction")))
        rows = session.exec(select(snap, analysis).outerjoin(analysis, join).where(snap.user_id == user,
            snap.league_id == league, snap.first_seen >= since).order_by(snap.first_seen.desc(), snap.player_id, snap.auction)
            .limit(500)).all()
        for snapshot, record in rows:
            inputs, result = (record.inputs, record.result) if record else ({}, {})
            kind, net, finance = classify(snapshot.reason, inputs, result)
            outcome = result.get("outcomes", {}).get("standard")
            real = bool(result.get("own"))
            if real or (finance == "feasible" and outcome in ("won", "lost")):
                learning.append(((snapshot.player_id, snapshot.auction), real, real or outcome == "won",
                                 (now - snapshot.first_seen).total_seconds() / 86400))
            categories[kind] += 1
            finance_counts[finance] += 1
            groups[(snapshot.reason, kind, finance)].append(net)
            for variant in ("minimum", "defensive", "standard", "aggressive", "ev"):
                outcome = result.get("outcomes", {}).get(variant, "unknown" if variant in inputs.get("bids", {}) else "unavailable")
                variants[variant][outcome] += 1
            cost = result.get("winner_price") if result.get("own") else inputs.get("bids", {}).get("standard")
            if cost and (result.get("own") or result.get("outcomes", {}).get("standard") == "won"):
                for strategy, proceeds in result.get("exits", {}).items():
                    exits[strategy].append(proceeds - cost)
        profits = session.exec(select(TradeLog.profit).where(TradeLog.user_id == user, TradeLog.league_id == league,
            TradeLog.kind == "sell", TradeLog.status == "sold", TradeLog.at >= since, TradeLog.profit.is_not(None))).all()
    def stats(values):
        known = [v for v in values if v is not None]
        return {"count": len(values), "sum": sum(known) if known else None, "median": median(known) if known else None}
    return {"observed": len(rows), "learning": weighted_win_rate(learning), "days": 30, "limit": 500, "categories": categories, "finance": finance_counts,
            "realized": stats(profits), "reasons": [{"reason": r, "category": c, "finance": f, **stats(v)}
                for (r, c, f), v in sorted(groups.items())], "bids": variants,
            "sales": {k: stats(v) for k, v in exits.items()}}
