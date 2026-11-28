"""Offline shadow settlement. All inputs come from the current round or local storage."""

from collections import defaultdict
from datetime import datetime, timedelta

from sqlmodel import Session, select

from core.shadow_intelligence import AuctionEvidence, bid_variants, settle_bids
from db.models import ShadowAnalysis, Transfer


def freeze(user, league, pid, auction, values, listing, extra, deadline, trailing, now):
    end = values.get("expires_at")
    if end is None and listing and listing.expires_in is not None:
        end = now + timedelta(seconds=listing.expires_in)
    floor = values.get("min_bid") or max(values.get("price") or 0, values.get("value") or 0)
    bids = bid_variants(floor, values.get("hypothetical_bid"), None) if floor > 0 else {}
    if extra.get("ev") and extra["ev"] >= bids.get("minimum", 0):
        bids["ev"] = extra["ev"]
    return ShadowAnalysis(user_id=user, league_id=league, player_id=pid, auction=auction,
        next_check=end + timedelta(seconds=2) if end else None, inputs={
            "bids": bids, "end": end.isoformat() if end else None, "seller": listing.seller.id if listing and listing.seller else None,
            "listed": bool(listing and listing.listed_at), "cap": extra.get("cap"),
            "ratio": values.get("sell_ratio"), "deadline": deadline, "trailing": trailing,
            "no_buyer": bool(listing and listing.seller is None and listing.expires_in == 0 and listing.offer_count == 0),
        })


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
    for row, end in zip(rows, ends, strict=True):
        data = row.inputs
        matches = [s for s in transfers[row.player_id] if abs(s.date - end) <= jitter]
        sale = matches[0] if len(matches) == 1 and data["listed"] else None
        if sale and (not sale.buyer_id or sale.seller_id != data["seller"] or
                     (sale.seller and not sale.seller_id) or sale.price <= 0):
            sale = None
        own = sale is not None and sale.buyer_id == user
        evidence = AuctionEvidence(sale.price if sale and not own else None, bool(not matches and data["no_buyer"]))
        row.result = {"outcomes": {v.name: v.outcome for v in settle_bids(data["bids"], evidence)},
                      "winner_price": sale.price if sale else None, "own": own}
        row.next_check = None if sale or evidence.confirmed_no_buyer or now >= end + timedelta(days=2) else now + timedelta(hours=1)
