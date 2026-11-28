"""One bounded, atomic archive transaction per round. The caller owns the commit."""

from collections import Counter, defaultdict

from sqlalchemy import and_, tuple_
from sqlmodel import delete, select

from core import analytics, coach
from core.shadow_intelligence import classify
from db.models import DecisionSnapshot, ShadowAnalysis, ShadowDaily

BATCH = 256


def archive_batch(session, user, league, cutoff):
    snap, analysis = DecisionSnapshot, ShadowAnalysis
    join = and_(*(getattr(snap, k) == getattr(analysis, k) for k in ("user_id", "league_id", "player_id", "auction")))
    rows = session.exec(select(snap, analysis).outerjoin(analysis, join).where(snap.user_id == user,
        snap.league_id == league, snap.first_seen < cutoff).order_by(snap.first_seen).limit(BATCH)).all()
    if not rows:
        return 0
    groups = defaultdict(Counter)
    keys = []
    for row, record in rows:
        key = (analytics.market_value_day(row.first_seen), row.reason, coach.price_class(row.value))
        kind = classify(row.reason, record.inputs, record.result)[0] if record else "unknown"
        groups[key][kind] += 1
        keys.append((row.player_id, row.auction))
    for (day, reason, bucket), counts in groups.items():
        entry = session.get(ShadowDaily, (user, league, day, reason, bucket))
        if entry is None:
            entry = ShadowDaily(user_id=user, league_id=league, day=day, reason=reason, price_class=bucket)
        entry.count += counts.total()
        entry.categories = dict(Counter(entry.categories) + counts)
        session.add(entry)
    for table in (analysis, snap):
        session.exec(delete(table).where(table.user_id == user, table.league_id == league,
            tuple_(table.player_id, table.auction).in_(keys)).execution_options(synchronize_session=False))
    return len(rows)
