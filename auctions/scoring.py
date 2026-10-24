"""The score (docs/PRODUCT.md §4).

    score = wP·clamp(1 − prix/budget_max) + wD·clamp(1 − délai/délai_max) + wT·(tags communs / tags demandés)

Each ratio is clamped to [0, 1] BEFORE weighting; no requested tag → skills ratio 1
for everyone. Weights are integers summing to 100 (default 40/30/30).
"""

from decimal import Decimal

DEFAULT_WEIGHTS = (40, 30, 30)


def _clamp(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def normalise_weights(wp, wd, ws) -> tuple[int, int, int]:
    """Ints from GET params → three non-negative ints summing to exactly 100.

    Anything unparsable, negative or all-zero falls back to DEFAULT_WEIGHTS.
    Rounding uses the largest-remainder method so the sum is always 100.
    """
    try:
        raw = [int(wp), int(wd), int(ws)]
    except (TypeError, ValueError):
        return DEFAULT_WEIGHTS
    if any(w < 0 for w in raw) or sum(raw) <= 0:
        return DEFAULT_WEIGHTS
    total = sum(raw)
    if total == 100:
        return tuple(raw)  # type: ignore[return-value]
    exact = [w * 100 / total for w in raw]
    floors = [int(e) for e in exact]
    remainder = 100 - sum(floors)
    order = sorted(range(3), key=lambda i: (exact[i] - floors[i], -raw[i]), reverse=True)
    for i in order[:remainder]:
        floors[i] += 1
    return tuple(floors)  # type: ignore[return-value]


def ratios(bid, need) -> dict:
    """The three clamped ratios in [0, 1] — what the sliders re-weight in the browser."""
    budget = float(need.budget_max) if need.budget_max else 0.0
    price_ratio = _clamp(1 - float(bid.price) / budget) if budget > 0 else 0.0
    delay_ratio = _clamp(1 - bid.delay_days / need.delay_max_days) if need.delay_max_days else 0.0
    wanted = [t for t in (need.tags or []) if t]
    if wanted:
        common = len(set(bid.tags or []) & set(wanted))
        skills_ratio = _clamp(common / len(wanted))
    else:
        skills_ratio = 1.0
    return {"price_ratio": price_ratio, "delay_ratio": delay_ratio, "skills_ratio": skills_ratio}


def score_bid(bid, need, weights=DEFAULT_WEIGHTS) -> dict:
    """→ {total, price_part, delay_part, skills_part, price_ratio, delay_ratio, skills_ratio}."""
    wp, wd, ws = weights
    r = ratios(bid, need)
    price_part = wp * r["price_ratio"]
    delay_part = wd * r["delay_ratio"]
    skills_part = ws * r["skills_ratio"]
    return {
        "total": price_part + delay_part + skills_part,
        "price_part": price_part,
        "delay_part": delay_part,
        "skills_part": skills_part,
        **r,
    }


def rank_bids(need, weights=DEFAULT_WEIGHTS, bids=None) -> list[tuple]:
    """[(bid, score_dict), …] best first. Ties: cheaper first, then the earlier bid."""
    if bids is None:
        bids = list(need.ranked_bid_qs())
    scored = [(bid, score_bid(bid, need, weights)) for bid in bids]
    scored.sort(key=lambda item: (-round(item[1]["total"], 6), Decimal(item[0].price), item[0].created_at, item[0].pk))
    return scored
