from binance.client import Client
from config import (
    ORDERBOOK_LIMIT,
    OB_STRONG_LONG_RATIO, OB_MODERATE_LONG_RATIO,
    OB_STRONG_SHORT_RATIO, OB_MODERATE_SHORT_RATIO,
    OB_WALL_CONCENTRATION_THRESHOLD,
    REWARD_TO_RISK,
)


def _parse_levels(raw: list) -> list:
    return [(float(p), float(q)) for p, q in raw]


def _wall_concentration(levels: list, top_n: int = 3) -> float:
    """
    Fraction of total qty held by the top-N levels (by qty).
    A high value means liquidity is concentrated → strong wall signal.
    """
    if not levels:
        return 0.0
    total = sum(q for _, q in levels)
    if total == 0:
        return 0.0
    top = sorted(levels, key=lambda x: x[1], reverse=True)[:top_n]
    return sum(q for _, q in top) / total


def analyze_orderbook(client: Client, symbol: str) -> dict:
    """
    PRIMARY signal generator. Derives LONG / SHORT / NEUTRAL directly
    from order-book structure.

    Signal logic (in priority order):
      1. bid/ask volume ratio  →  base signal + confidence level
      2. Wall concentration    →  upgrades confidence to HIGH when aligned
      3. Wide spread           →  downgrades HIGH → MODERATE (cost risk)

    Returns
    -------
    signal          : "LONG" | "SHORT" | "NEUTRAL"
    confidence      : "HIGH" | "MODERATE" | "LOW"
    bid_ask_ratio   : float
    imbalance_signal: "BUY_PRESSURE" | "SELL_PRESSURE" | "BALANCED"
    spread_pct      : float
    best_bid / best_ask
    bid_wall_concentration / ask_wall_concentration
    strongest_bid_wall / strongest_ask_wall  : {price, qty}
    suggested_entry / suggested_sl_long / suggested_sl_short
    suggested_tp_long / suggested_tp_short
    total_bid_qty / total_ask_qty
    """
    book = client.futures_order_book(symbol=symbol, limit=ORDERBOOK_LIMIT)
    bids = _parse_levels(book["bids"])
    asks = _parse_levels(book["asks"])

    if not bids or not asks:
        return {
            "symbol": symbol, "signal": "NEUTRAL", "confidence": "LOW",
            "error": "Empty order book",
        }

    best_bid  = bids[0][0]
    best_ask  = asks[0][0]
    spread    = best_ask - best_bid
    spread_pct = (spread / best_bid * 100) if best_bid > 0 else 0
    mid       = (best_bid + best_ask) / 2

    total_bid = sum(q for _, q in bids)
    total_ask = sum(q for _, q in asks)
    ratio     = total_bid / total_ask if total_ask > 0 else float("inf")

    bid_conc = _wall_concentration(bids)
    ask_conc = _wall_concentration(asks)

    strongest_bid = max(bids, key=lambda x: x[1])
    strongest_ask = max(asks, key=lambda x: x[1])

    # ── Step 1: base signal from ratio ─────────────────────────────────────
    if ratio >= OB_STRONG_LONG_RATIO:
        signal, confidence = "LONG",  "HIGH"
    elif ratio >= OB_MODERATE_LONG_RATIO:
        signal, confidence = "LONG",  "MODERATE"
    elif ratio <= OB_STRONG_SHORT_RATIO:
        signal, confidence = "SHORT", "HIGH"
    elif ratio <= OB_MODERATE_SHORT_RATIO:
        signal, confidence = "SHORT", "MODERATE"
    else:
        signal, confidence = "NEUTRAL", "LOW"

    # ── Step 2: wall concentration upgrade ─────────────────────────────────
    if signal == "LONG"  and bid_conc >= OB_WALL_CONCENTRATION_THRESHOLD:
        confidence = "HIGH"
    elif signal == "SHORT" and ask_conc >= OB_WALL_CONCENTRATION_THRESHOLD:
        confidence = "HIGH"

    # ── Step 3: wide spread downgrade ──────────────────────────────────────
    if spread_pct > 0.1 and confidence == "HIGH":
        confidence = "MODERATE"

    # ── Entry / SL / TP ────────────────────────────────────────────────────
    if signal == "LONG":
        suggested_entry    = round(best_bid, 6)
        suggested_sl_long  = round(strongest_bid[0] * 0.998, 6)
        suggested_sl_short = None
        sl_dist            = suggested_entry - suggested_sl_long
        suggested_tp_long  = round(suggested_entry + sl_dist * REWARD_TO_RISK, 6)
        suggested_tp_short = None
    elif signal == "SHORT":
        suggested_entry    = round(best_ask, 6)
        suggested_sl_short = round(strongest_ask[0] * 1.002, 6)
        suggested_sl_long  = None
        sl_dist            = suggested_sl_short - suggested_entry
        suggested_tp_short = round(suggested_entry - sl_dist * REWARD_TO_RISK, 6)
        suggested_tp_long  = None
    else:
        suggested_entry    = round(mid, 6)
        suggested_sl_long  = suggested_sl_short  = None
        suggested_tp_long  = suggested_tp_short  = None

    imbalance_map = {"LONG": "BUY_PRESSURE", "SHORT": "SELL_PRESSURE", "NEUTRAL": "BALANCED"}

    return {
        "symbol":                  symbol,
        "signal":                  signal,
        "confidence":              confidence,
        "bid_ask_ratio":           round(ratio, 4),
        "imbalance_signal":        imbalance_map[signal],
        "best_bid":                best_bid,
        "best_ask":                best_ask,
        "spread_pct":              round(spread_pct, 5),
        "total_bid_qty":           round(total_bid, 4),
        "total_ask_qty":           round(total_ask, 4),
        "bid_wall_concentration":  round(bid_conc, 4),
        "ask_wall_concentration":  round(ask_conc, 4),
        "strongest_bid_wall":      {"price": strongest_bid[0], "qty": strongest_bid[1]},
        "strongest_ask_wall":      {"price": strongest_ask[0], "qty": strongest_ask[1]},
        "suggested_entry":         suggested_entry,
        "suggested_sl_long":       suggested_sl_long,
        "suggested_sl_short":      suggested_sl_short,
        "suggested_tp_long":       suggested_tp_long,
        "suggested_tp_short":      suggested_tp_short,
    }
