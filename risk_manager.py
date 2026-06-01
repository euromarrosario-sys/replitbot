"""
risk_manager.py

Handles:
  • Adaptive position sizing
      1. Calculate position at target risk (RISK_PER_TRADE_PCT % of balance)
      2. Compute required margin
      3. If margin > MAX_MARGIN_PCT: scale quantity down to fit the limit
         → recalculate actual dollar risk, costs, net profit
      4. Reject only if the scaled-down position fails R:R or net-profit gate
  • SL rule: ATR sets the MINIMUM distance; OB can only widen it
      LONG : sl_final = min(sl_atr_price, sl_ob_price)  [lower = farther]
      SHORT: sl_final = max(sl_atr_price, sl_ob_price)  [higher = farther]
  • Net profit gate after scaling
  • Trailing stop: activates only once position is past breakeven
"""

from binance.client import Client
from config import (
    RISK_PER_TRADE_PCT,
    LEVERAGE,
    REWARD_TO_RISK,
    ATR_SL_MULTIPLIER,
    MAX_MARGIN_PCT,
    TAKER_FEE_PCT,
    SLIPPAGE_PCT,
    SAFETY_MARGIN_PCT,
    MIN_NET_PROFIT_USD,
    TRAILING_STOP_PCT,
    PAPER_BALANCE_USD,
)


# ── Account ──────────────────────────────────────────────────────────────────

def get_account_balance(client: Client, asset: str = "USDT") -> float:
    if PAPER_BALANCE_USD > 0:
        return PAPER_BALANCE_USD
    try:
        account   = client.futures_account()
        available = float(account["availableBalance"])
        return available if available > 0 else PAPER_BALANCE_USD
    except Exception:
        pass
    return PAPER_BALANCE_USD


# ── Cost model ───────────────────────────────────────────────────────────────

def calculate_trade_costs(notional: float) -> dict:
    """Full round-trip cost breakdown (entry + exit) for a given notional."""
    fee_rate    = TAKER_FEE_PCT     / 100
    slip_rate   = SLIPPAGE_PCT      / 100
    safety_rate = SAFETY_MARGIN_PCT / 100

    entry_fee     = notional * fee_rate
    exit_fee      = notional * fee_rate
    slippage_cost = notional * slip_rate   * 2
    safety_cost   = notional * safety_rate * 2
    total_cost    = entry_fee + exit_fee + slippage_cost + safety_cost

    return {
        "entry_fee":     round(entry_fee,     6),
        "exit_fee":      round(exit_fee,      6),
        "slippage_cost": round(slippage_cost, 6),
        "safety_cost":   round(safety_cost,   6),
        "total_cost":    round(total_cost,    6),
    }


def calculate_net_profit(
    signal: str,
    quantity: float,
    entry_price: float,
    take_profit: float,
    costs: dict,
) -> dict:
    """Expected P&L at TP minus all costs, plus breakeven price."""
    if signal == "LONG":
        gross_profit    = (take_profit - entry_price) * quantity
        breakeven_price = entry_price + costs["total_cost"] / quantity
    else:
        gross_profit    = (entry_price - take_profit) * quantity
        breakeven_price = entry_price - costs["total_cost"] / quantity

    net_profit = gross_profit - costs["total_cost"]

    return {
        "gross_profit":    round(gross_profit,    6),
        "net_profit":      round(net_profit,      6),
        "breakeven_price": round(breakeven_price, 6),
    }


# ── Position sizing (adaptive) ───────────────────────────────────────────────

def calculate_position(
    client: Client,
    signal: str,
    entry_price: float,
    atr: float,
    ob_sl_long:      float | None = None,
    ob_sl_short:     float | None = None,
    ob_tp_long:      float | None = None,
    ob_tp_short:     float | None = None,
    risk_pct_override: float | None = None,
) -> dict | None:
    """
    Full position calculation with adaptive sizing.

    SL rule  (sl_final_dist = max(atr_dist, ob_dist)):
      LONG : sl_final = min(sl_atr_price, ob_sl_price)   [farther = lower]
      SHORT: sl_final = max(sl_atr_price, ob_sl_price)   [farther = higher]

    Adaptive sizing:
      1. Compute target quantity from RISK_PER_TRADE_PCT.
      2. If resulting margin > MAX_MARGIN_PCT of balance:
         - Scale quantity down to the maximum allowed by the margin limit.
         - Recompute actual dollar risk (= scaled_qty × sl_distance).
         - Flag adjustment reason and reduction factor in the returned dict.
      3. Reject only if scaled position fails R:R or net-profit gate.

    Returns None if the geometry is degenerate (zero SL, R:R impossible).
    """
    if signal not in ("LONG", "SHORT"):
        return None

    balance = get_account_balance(client)
    if balance <= 0:
        return None

    atr_sl_distance = atr * ATR_SL_MULTIPLIER

    # ── Stop-loss (ATR floor, OB can only widen) ─────────────────────────────
    if signal == "LONG":
        sl_atr_price = entry_price - atr_sl_distance
        ob_sl_dist   = (entry_price - ob_sl_long) if ob_sl_long is not None else None
        stop_loss    = min(sl_atr_price, ob_sl_long) if ob_sl_long is not None else sl_atr_price
    else:  # SHORT
        sl_atr_price = entry_price + atr_sl_distance
        ob_sl_dist   = (ob_sl_short - entry_price) if ob_sl_short is not None else None
        stop_loss    = max(sl_atr_price, ob_sl_short) if ob_sl_short is not None else sl_atr_price

    stop_loss   = round(stop_loss, 6)
    sl_distance = abs(entry_price - stop_loss)
    if sl_distance == 0:
        return None

    sl_source = (
        "OB" if ob_sl_dist is not None and ob_sl_dist > atr_sl_distance
        else "ATR"
    )

    # ── Take-profit ──────────────────────────────────────────────────────────
    tp_distance = sl_distance * REWARD_TO_RISK
    if signal == "LONG":
        tp_atr      = entry_price + tp_distance
        take_profit = max(tp_atr, ob_tp_long) if ob_tp_long else tp_atr
    else:
        tp_atr      = entry_price - tp_distance
        take_profit = min(tp_atr, ob_tp_short) if ob_tp_short else tp_atr

    take_profit    = round(take_profit, 6)
    actual_tp_dist = abs(take_profit - entry_price)
    rr_ratio       = actual_tp_dist / sl_distance if sl_distance > 0 else 0

    if rr_ratio < REWARD_TO_RISK:
        return None

    # ── Target sizing (from RISK_PER_TRADE_PCT, or override from RiskEngine) ──
    effective_risk_pct = risk_pct_override if risk_pct_override is not None else RISK_PER_TRADE_PCT
    dollar_risk_target = balance * (effective_risk_pct / 100)
    qty_target         = dollar_risk_target / sl_distance
    notional_target    = qty_target * entry_price
    margin_target      = notional_target / LEVERAGE
    margin_target_pct  = (margin_target / balance) * 100

    # ── Adaptive scaling ─────────────────────────────────────────────────────
    max_margin_usd = balance * (MAX_MARGIN_PCT / 100)
    adjustment_reason  = "none"
    reduction_factor   = 1.0

    if margin_target > max_margin_usd:
        # Maximum quantity that fits within the margin limit
        max_notional    = max_margin_usd * LEVERAGE
        qty_scaled      = max_notional / entry_price
        reduction_factor = qty_scaled / qty_target          # < 1.0
        adjustment_reason = (
            f"Target margin {margin_target_pct:.1f}% > limit {MAX_MARGIN_PCT}%; "
            f"scaled down by factor {reduction_factor:.4f}"
        )
        quantity    = qty_scaled
    else:
        quantity    = qty_target

    notional         = quantity * entry_price
    margin_used      = notional / LEVERAGE
    margin_pct       = (margin_used / balance) * 100
    dollar_risk_actual = quantity * sl_distance    # actual risk after scaling

    # ── Costs + net profit (on scaled notional) ──────────────────────────────
    costs      = calculate_trade_costs(notional)
    net_result = calculate_net_profit(signal, quantity, entry_price, take_profit, costs)

    return {
        "signal":        signal,
        "entry_price":   round(entry_price,       6),
        "stop_loss":     stop_loss,
        "take_profit":   take_profit,
        # SL breakdown
        "atr":           round(atr,               6),
        "sl_atr_dist":   round(atr_sl_distance,   6),
        "sl_ob_dist":    round(ob_sl_dist,         6) if ob_sl_dist is not None else None,
        "sl_source":     sl_source,
        "sl_distance":   round(sl_distance,       6),
        "tp_distance":   round(actual_tp_dist,    6),
        "rr_ratio":      round(rr_ratio,           2),
        # Sizing
        "quantity":            round(quantity,           6),
        "notional":            round(notional,           2),
        "margin_used":         round(margin_used,        2),
        "margin_pct":          round(margin_pct,         2),
        # Risk traceability
        "dollar_risk_target":  round(dollar_risk_target, 4),
        "dollar_risk_actual":  round(dollar_risk_actual, 4),
        "dollar_risk":         round(dollar_risk_actual, 4),   # kept for legacy log field
        "balance":             round(balance,             2),
        "leverage":            LEVERAGE,
        "adjustment_reason":   adjustment_reason,
        "reduction_factor":    round(reduction_factor,    6),
        **costs,
        **net_result,
    }


# ── Trade gate ───────────────────────────────────────────────────────────────

def is_trade_allowed(position: dict | None) -> tuple[bool, str]:
    """
    Final gate after adaptive sizing.
    Rejects if:
      1. position is None (degenerate geometry)
      2. rr_ratio < REWARD_TO_RISK  (prices changed between calc and gate)
      3. net_profit < MIN_NET_PROFIT_USD  (scaled notional too small to cover costs)
    Margin is NOT a rejection criterion here — sizing already adapted to the limit.
    """
    if position is None:
        return False, "No valid position calculated"

    if position["rr_ratio"] < REWARD_TO_RISK:
        return False, f"R:R {position['rr_ratio']} below minimum {REWARD_TO_RISK}"

    if position["net_profit"] < MIN_NET_PROFIT_USD:
        return False, (
            f"Net profit ${position['net_profit']:.4f} below "
            f"minimum ${MIN_NET_PROFIT_USD:.2f} "
            f"(costs=${position['total_cost']:.4f}, notional=${position['notional']:.2f})"
        )

    return True, "Trade approved"


# ── Trailing stop (paper mode) ────────────────────────────────────────────────

def update_trailing_stop(
    position: dict,
    current_price: float,
    trail_pct_override: float | None = None,
) -> tuple[dict, bool]:
    """
    Update the trailing stop for an open paper position.
    Trail activates ONLY once current_price crosses breakeven_price.
    Once active, SL moves in the favorable direction only (never reversed).

    trail_pct_override: effective trail % as a decimal (e.g. 0.005 = 0.5%).
    When None, falls back to TRAILING_STOP_PCT from config.
    """
    signal          = position["signal"]
    breakeven_price = position["breakeven_price"]
    trail_pct       = trail_pct_override if trail_pct_override is not None else TRAILING_STOP_PCT / 100
    just_activated  = False

    if "extreme_price" not in position:
        position["extreme_price"]   = position["entry_price"]
        position["trailing_active"] = False

    was_active = position["trailing_active"]

    if signal == "LONG":
        if current_price > position["extreme_price"]:
            position["extreme_price"] = current_price
        if not was_active and current_price > breakeven_price:
            position["trailing_active"] = True
            just_activated = True
        if position["trailing_active"]:
            new_sl = round(position["extreme_price"] * (1 - trail_pct), 6)
            if new_sl > position["stop_loss"]:
                position["stop_loss"] = new_sl
    else:  # SHORT
        if current_price < position["extreme_price"]:
            position["extreme_price"] = current_price
        if not was_active and current_price < breakeven_price:
            position["trailing_active"] = True
            just_activated = True
        if position["trailing_active"]:
            new_sl = round(position["extreme_price"] * (1 + trail_pct), 6)
            if new_sl < position["stop_loss"]:
                position["stop_loss"] = new_sl

    return position, just_activated


def check_position_exit(position: dict, current_price: float) -> tuple[bool, str]:
    """Check whether a paper position should close at current_price."""
    signal = position["signal"]
    sl     = position["stop_loss"]
    tp     = position["take_profit"]

    if signal == "LONG":
        if current_price <= sl:
            return True, f"SL hit @ {current_price} (SL={sl})"
        if current_price >= tp:
            return True, f"TP hit @ {current_price} (TP={tp})"
    else:
        if current_price >= sl:
            return True, f"SL hit @ {current_price} (SL={sl})"
        if current_price <= tp:
            return True, f"TP hit @ {current_price} (TP={tp})"

    return False, ""
