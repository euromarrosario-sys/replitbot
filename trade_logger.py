"""
trade_logger.py

Colour-coded console output + CSV persistence for:
  • Order-book scan results (primary)
  • Indicator filter verdicts (secondary)
  • Trade decisions with full cost breakdown (including SL breakdown)
  • Trailing stop updates
  • Paper position closes with realised P&L
"""

import csv
import os
from datetime import datetime, timezone
from config import LOG_DIR, TRADES_CSV, SIGNALS_CSV, POSITIONS_CSV, SUMMARY_CSV

# ── ANSI colours ────────────────────────────────────────────────────────────
_R  = "\033[0m"
_G  = "\033[92m"   # green
_RD = "\033[91m"   # red
_Y  = "\033[93m"   # yellow
_C  = "\033[96m"   # cyan
_GR = "\033[90m"   # grey
_B  = "\033[1m"    # bold
_M  = "\033[95m"   # magenta  (trailing stop)

_SIG_COLOUR  = {"LONG": _G, "SHORT": _RD, "NEUTRAL": _GR, "ERROR": _Y}
_CONF_COLOUR = {"HIGH": _G, "MODERATE": _Y, "LOW": _GR}

# ── CSV field lists ──────────────────────────────────────────────────────────
_SIGNALS_FIELDS = [
    "timestamp", "symbol", "ob_signal", "ob_confidence", "bid_ask_ratio",
    "spread_pct", "bid_wall_conc", "ask_wall_conc",
    "indicator_filter_passed", "filter_reason",
    "rsi", "ema_fast", "ema_slow", "atr", "volume_ratio",
]

_TRADES_FIELDS = [
    "timestamp", "symbol", "signal",
    "entry_price", "stop_loss", "take_profit",
    # SL breakdown
    "atr", "sl_atr_dist", "sl_ob_dist", "sl_source", "sl_distance",
    "tp_distance", "rr_ratio",
    # Sizing (adaptive)
    "quantity", "notional", "margin_used", "margin_pct",
    "dollar_risk_target", "dollar_risk_actual", "dollar_risk",
    "balance", "leverage",
    "adjustment_reason", "reduction_factor",
    # Costs
    "entry_fee", "exit_fee", "slippage_cost", "safety_cost", "total_cost",
    # Profit
    "gross_profit", "net_profit", "breakeven_price",
    # Meta
    "ob_confidence", "ob_imbalance",
    "allowed", "rejection_reason",
]

_POSITIONS_FIELDS = [
    "timestamp", "symbol", "signal", "entry_price",
    "close_price", "stop_loss_at_close", "take_profit",
    "quantity", "gross_pnl", "net_pnl", "total_cost",
    "trailing_active", "exit_reason",
]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _ensure(path: str, fields: list) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=fields).writeheader()


def _append(path: str, fields: list, row: dict) -> None:
    _ensure(path, fields)
    with open(path, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=fields, extrasaction="ignore").writerow(row)


# ── Public log functions ─────────────────────────────────────────────────────

def log_ob_scan(ob: dict, indicators: dict | None, filter_passed: bool, filter_reason: str) -> None:
    """Log one order-book scan result with indicator filter verdict."""
    ts     = _now()
    sig    = ob.get("signal",     "?")
    conf   = ob.get("confidence", "?")
    sym    = ob["symbol"]
    ratio  = ob.get("bid_ask_ratio", 0)
    spread = ob.get("spread_pct", 0)

    sig_col  = _SIG_COLOUR.get(sig,  _GR)
    conf_col = _CONF_COLOUR.get(conf, _GR)

    filter_str = ""
    if sig in ("LONG", "SHORT"):
        fp_col     = _G if filter_passed else _RD
        fp_icon    = "✔" if filter_passed else "✘"
        filter_str = f"  filter={fp_col}{fp_icon} {filter_reason}{_R}"

    print(
        f"  {sig_col}{_B}{sig:<8}{_R}"
        f"{conf_col}[{conf}]{_R}  "
        f"{sym:<10}  ratio={ratio:<7}  spread={spread:.4f}%"
        f"{filter_str}"
    )

    row = {
        "timestamp":               ts,
        "symbol":                  sym,
        "ob_signal":               sig,
        "ob_confidence":           conf,
        "bid_ask_ratio":           ratio,
        "spread_pct":              spread,
        "bid_wall_conc":           ob.get("bid_wall_concentration"),
        "ask_wall_conc":           ob.get("ask_wall_concentration"),
        "indicator_filter_passed": filter_passed,
        "filter_reason":           filter_reason,
        "rsi":                     indicators.get("rsi")          if indicators else None,
        "ema_fast":                indicators.get("ema_fast")     if indicators else None,
        "ema_slow":                indicators.get("ema_slow")     if indicators else None,
        "atr":                     indicators.get("atr")          if indicators else None,
        "volume_ratio":            indicators.get("volume_ratio") if indicators else None,
    }
    _append(SIGNALS_CSV, _SIGNALS_FIELDS, row)


def log_scan_header(cycle: int) -> None:
    ts = _now()
    print(f"\n{_B}{_C}{'─'*62}{_R}")
    print(f"{_B}{_C}  ORDER-BOOK SCAN  —  Cycle #{cycle}  —  {ts}{_R}")
    print(f"{_B}{_C}{'─'*62}{_R}")


def log_scan_footer(longs: int, shorts: int, neutrals: int, errors: int) -> None:
    print(
        f"  {_GR}Summary →{_R} "
        f"{_G}LONG:{longs}{_R}  "
        f"{_RD}SHORT:{shorts}{_R}  "
        f"NEUTRAL:{neutrals}  "
        f"{_Y}ERROR:{errors}{_R}\n"
    )


def log_trade_decision(
    symbol: str,
    position: dict | None,
    ob: dict | None,
    allowed: bool,
    rejection_reason: str = "",
) -> None:
    """Log a trade approval or rejection with full cost and SL breakdown."""
    ts       = _now()
    ob_conf  = ob.get("confidence",      "N/A") if ob else "N/A"
    ob_imbal = ob.get("imbalance_signal","N/A") if ob else "N/A"

    if allowed and position:
        col       = _G if position["signal"] == "LONG" else _RD
        sl_ob_str = (
            f"OB_dist={position['sl_ob_dist']:.6f}  "
            if position.get("sl_ob_dist") is not None else ""
        )

        # Adaptive sizing display
        rf = position.get("reduction_factor", 1.0)
        adj_reason = position.get("adjustment_reason", "none")
        if adj_reason != "none" and rf < 1.0:
            sizing_str = (
                f"\n    {_Y}⟳ ADAPTIVE SIZING:{_R}  "
                f"target_risk=${position['dollar_risk_target']:.2f}  "
                f"actual_risk=${position['dollar_risk_actual']:.2f}  "
                f"factor={rf:.4f}  ({adj_reason})"
            )
        else:
            sizing_str = (
                f"\n    {_GR}Sizing: target_risk=${position['dollar_risk_target']:.2f}  "
                f"(no adjustment needed){_R}"
            )

        print(
            f"\n{col}{_B}  ✔ TRADE APPROVED{_R}  {symbol}  {position['signal']}\n"
            f"    Entry={position['entry_price']}  "
            f"SL={position['stop_loss']}  "
            f"TP={position['take_profit']}"
            f"{sizing_str}\n"
            f"    {_Y}SL breakdown:{_R}  "
            f"ATR={position['atr']:.6f}  "
            f"ATR_dist={position['sl_atr_dist']:.6f}  "
            f"{sl_ob_str}"
            f"→ Final_dist={position['sl_distance']:.6f}  "
            f"[src: {position.get('sl_source','ATR')}]\n"
            f"    R:R={position['rr_ratio']}  "
            f"Qty={position['quantity']}  "
            f"Notional=${position['notional']}  "
            f"Margin=${position['margin_used']} ({position['margin_pct']:.1f}%)\n"
            f"    {_Y}Costs: fees=${position['entry_fee']+position['exit_fee']:.4f}  "
            f"slip=${position['slippage_cost']:.4f}  "
            f"safety=${position['safety_cost']:.4f}  "
            f"total=${position['total_cost']:.4f}{_R}\n"
            f"    {_G}Gross TP profit=${position['gross_profit']:.4f}  "
            f"Net profit=${position['net_profit']:.4f}  "
            f"Breakeven={position['breakeven_price']}{_R}"
        )
    else:
        print(f"  {_Y}✘ SKIPPED{_R}  {symbol}  —  {rejection_reason}")

    _append(TRADES_CSV, _TRADES_FIELDS, {
        "timestamp":        ts,
        "symbol":           symbol,
        "ob_confidence":    ob_conf,
        "ob_imbalance":     ob_imbal,
        "allowed":          allowed,
        "rejection_reason": rejection_reason,
        **(position or {}),
    })


def log_trailing_activated(symbol: str, signal: str, breakeven: float,
                            current_price: float, new_sl: float) -> None:
    print(
        f"  {_M}{_B}⟳ TRAILING STOP ACTIVATED{_R}  {symbol} [{signal}]  "
        f"price={current_price} crossed breakeven={breakeven}  "
        f"trail SL={new_sl}"
    )


def log_trailing_update(symbol: str, signal: str, old_sl: float,
                         new_sl: float, extreme: float) -> None:
    print(
        f"  {_M}⟳ trail SL moved{_R}  {symbol} [{signal}]  "
        f"{old_sl} → {new_sl}  (extreme={extreme})"
    )


def log_position_close(position: dict, close_price: float, exit_reason: str) -> None:
    """Log a paper position being closed with realised P&L."""
    ts     = _now()
    signal = position["signal"]
    entry  = position["entry_price"]
    qty    = position["quantity"]
    costs  = position.get("total_cost", 0)

    if signal == "LONG":
        gross_pnl = (close_price - entry) * qty
    else:
        gross_pnl = (entry - close_price) * qty

    net_pnl = gross_pnl - costs
    pnl_col = _G if net_pnl >= 0 else _RD
    icon    = "✔ WIN" if net_pnl >= 0 else "✘ LOSS"

    print(
        f"\n  {pnl_col}{_B}{icon}{_R}  {position['symbol']} [{signal}]  "
        f"close={close_price}  "
        f"gross={gross_pnl:+.4f}  net={pnl_col}{net_pnl:+.4f}{_R}  "
        f"({exit_reason})"
    )

    _append(POSITIONS_CSV, _POSITIONS_FIELDS, {
        "timestamp":          ts,
        "symbol":             position["symbol"],
        "signal":             signal,
        "entry_price":        entry,
        "close_price":        close_price,
        "stop_loss_at_close": position["stop_loss"],
        "take_profit":        position["take_profit"],
        "quantity":           qty,
        "gross_pnl":          round(gross_pnl, 6),
        "net_pnl":            round(net_pnl,   6),
        "total_cost":         costs,
        "trailing_active":    position.get("trailing_active", False),
        "exit_reason":        exit_reason,
    })


def log_open_positions(positions: dict) -> None:
    if not positions:
        return
    print(f"\n  {_B}Open paper positions:{_R}")
    for sym, pos in positions.items():
        trail_str = f"{_M}trail-active{_R}" if pos.get("trailing_active") else "trail-pending"
        col       = _G if pos["signal"] == "LONG" else _RD
        print(
            f"    {col}{pos['signal']:<6}{_R} {sym:<10}  "
            f"entry={pos['entry_price']}  SL={pos['stop_loss']}  "
            f"TP={pos['take_profit']}  {trail_str}"
        )


def log_error(symbol: str, message: str) -> None:
    print(f"  {_Y}⚠ ERROR  {symbol}: {message}{_R}")


def log_info(message: str) -> None:
    print(f"  {_GR}{message}{_R}")


# ── Summary block (extended simulation) ──────────────────────────────────────

_SUMMARY_FIELDS = [
    "block", "start_cycle", "end_cycle", "timestamp",
    "trades_opened", "trades_closed",
    "win_count", "loss_count",
    "win_rate", "expectancy", "profit_factor",
    "max_drawdown", "total_net_pnl",
    "mark_to_market_closes",
]


def log_summary_block(
    block: int,
    start_cycle: int,
    end_cycle: int,
    trades_opened: int,
    closed_pnls: list[float],
    mark_to_market_closes: int,
) -> None:
    """
    Compute and persist aggregate metrics for one block of cycles.

    closed_pnls: list of net P&L values for all positions closed
                 during this block (natural closes + mark-to-market).
    mark_to_market_closes: how many of those were forced at block end.
    """
    ts = _now()

    wins   = [v for v in closed_pnls if v >= 0]
    losses = [v for v in closed_pnls if v < 0]
    n      = len(closed_pnls)

    win_count  = len(wins)
    loss_count = len(losses)
    win_rate   = win_count / n if n > 0 else 0.0
    expectancy = sum(closed_pnls) / n if n > 0 else 0.0
    total_pnl  = sum(closed_pnls)

    gross_wins   = sum(wins)
    gross_losses = abs(sum(losses))
    profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else (
        float("inf") if gross_wins > 0 else 0.0
    )
    if profit_factor == float("inf"):
        profit_factor = 9999.0

    # Max drawdown within the block (equity curve of block trades in order)
    peak = 0.0
    max_dd = 0.0
    running = 0.0
    for pnl in closed_pnls:
        running += pnl
        if running > peak:
            peak = running
        dd = peak - running
        if dd > max_dd:
            max_dd = dd

    row = {
        "block":                 block,
        "start_cycle":           start_cycle,
        "end_cycle":             end_cycle,
        "timestamp":             ts,
        "trades_opened":         trades_opened,
        "trades_closed":         n,
        "win_count":             win_count,
        "loss_count":            loss_count,
        "win_rate":              round(win_rate, 4),
        "expectancy":            round(expectancy, 4),
        "profit_factor":         round(profit_factor, 4),
        "max_drawdown":          round(max_dd, 4),
        "total_net_pnl":         round(total_pnl, 4),
        "mark_to_market_closes": mark_to_market_closes,
    }
    _append(SUMMARY_CSV, _SUMMARY_FIELDS, row)

    # Console output
    pf_col = _G if profit_factor >= 1.0 else _RD
    wr_col = _G if win_rate >= 0.5 else (_Y if n == 0 else _RD)
    ex_col = _G if expectancy >= 0 else _RD

    print(
        f"\n  {_B}{_C}▶ BLOCK #{block}{_R}  cycles {start_cycle}–{end_cycle}"
        f"  ({n} trades closed, {mark_to_market_closes} mark-to-mkt)\n"
        f"    Win rate  : {wr_col}{win_rate*100:.1f}%{_R}  "
        f"({win_count}W / {loss_count}L)\n"
        f"    Expectancy: {ex_col}${expectancy:+.2f}{_R} avg per trade\n"
        f"    Pft factor: {pf_col}{profit_factor:.2f}{_R}\n"
        f"    Max DD    : ${max_dd:.2f}\n"
        f"    Block P&L : {'$'+f'{total_pnl:+.2f}'}"
    )
