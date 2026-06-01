"""
run_test_cycles.py

Runs N scan cycles with no sleep, then prints a full statistics summary
of approved vs rejected signals including adaptive sizing details.

Usage: python run_test_cycles.py [cycles]   (default: 5)
"""

import sys
import os
import csv
from collections import defaultdict

import config
config.SCAN_INTERVAL_SECONDS = 0

from binance.client import Client
from main import build_client, run_cycle, update_open_positions
from trade_logger import log_info, log_open_positions
from config import (
    SYMBOLS, LEVERAGE, MAX_MARGIN_PCT, RISK_PER_TRADE_PCT,
    ATR_SL_MULTIPLIER, TRADES_CSV, SIGNALS_CSV,
    MIN_NET_PROFIT_USD, PAPER_BALANCE_USD,
)

_R  = "\033[0m"
_G  = "\033[92m"
_RD = "\033[91m"
_Y  = "\033[93m"
_C  = "\033[96m"
_B  = "\033[1m"
_GR = "\033[90m"
_M  = "\033[95m"


def load_csv(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def flt(row: dict, key: str) -> float:
    v = row.get(key, "")
    if v in ("", "None", None):
        return 0.0
    try:
        return float(v)
    except ValueError:
        return 0.0


def avg(rows: list[dict], key: str) -> float:
    vals = [flt(r, key) for r in rows if r.get(key) not in ("", "None", None)]
    return sum(vals) / len(vals) if vals else 0.0


def print_stats(cycles_run: int) -> None:
    signals = load_csv(SIGNALS_CSV)
    trades  = load_csv(TRADES_CSV)

    approved = [r for r in trades if r.get("allowed") == "True"]
    rejected = [r for r in trades if r.get("allowed") == "False"]
    adapted  = [r for r in approved if r.get("adjustment_reason", "none") != "none"
                                    and flt(r, "reduction_factor") < 1.0]

    print(f"\n{'='*72}")
    print(f"{_B}{_C}  STATISTICS  —  {cycles_run} cycle(s)  ×  {len(SYMBOLS)} symbols{_R}")
    print(f"{'='*72}")

    # ── Config ──────────────────────────────────────────────────────────────
    print(f"\n{_B}  CONFIG{_R}")
    print(f"    Leverage         : {LEVERAGE}×")
    print(f"    Target risk/trade: {RISK_PER_TRADE_PCT}% of account  "
          f"(${PAPER_BALANCE_USD * RISK_PER_TRADE_PCT / 100:,.2f})")
    print(f"    ATR multiplier   : {ATR_SL_MULTIPLIER}×  (minimum SL distance)")
    print(f"    Max margin/trade : {MAX_MARGIN_PCT}%  "
          f"(${PAPER_BALANCE_USD * MAX_MARGIN_PCT / 100:,.2f})")
    print(f"    Min net profit   : ${MIN_NET_PROFIT_USD}")
    print(f"    Paper balance    : ${PAPER_BALANCE_USD:,.2f}")
    print(f"    Adaptive sizing  : {_G}ON{_R}  "
          f"(scales down risk when margin > {MAX_MARGIN_PCT}%)")

    # ── OB signals ──────────────────────────────────────────────────────────
    total_scans  = len(signals)
    sig_counts   = defaultdict(int)
    conf_counts  = defaultdict(int)
    filter_pass  = sum(1 for r in signals if r.get("indicator_filter_passed") == "True")
    filter_fail  = sum(1 for r in signals if r.get("indicator_filter_passed") == "False")

    for r in signals:
        sig_counts[r.get("ob_signal", "?")] += 1
        conf_counts[r.get("ob_confidence", "?")] += 1

    print(f"\n{_B}  ORDER-BOOK SIGNALS  ({total_scans} scans){_R}")
    print(f"    {_G}LONG    : {sig_counts['LONG']}{_R}  |  "
          f"{_RD}SHORT   : {sig_counts['SHORT']}{_R}  |  "
          f"NEUTRAL : {sig_counts['NEUTRAL']}  |  "
          f"{_Y}ERROR   : {sig_counts['ERROR']}{_R}")
    print(f"    Confidence → HIGH:{conf_counts['HIGH']}  "
          f"MODERATE:{conf_counts['MODERATE']}  LOW:{conf_counts['LOW']}")
    if sig_counts["LONG"] + sig_counts["SHORT"] > 0:
        print(f"    Indicator filter → {_G}pass:{filter_pass}{_R}  {_RD}fail:{filter_fail}{_R}")

    # ── Trade decisions ─────────────────────────────────────────────────────
    total_trades = len(trades)
    reject_counts = defaultdict(int)
    for r in rejected:
        reason = r.get("rejection_reason", "Unknown")
        key = " ".join(reason.split()[:4])
        reject_counts[key] += 1

    print(f"\n{_B}  TRADE DECISIONS  ({total_trades} evaluated){_R}")
    print(f"    {_G}Approved         : {len(approved)}{_R}")
    print(f"    {_RD}Rejected         : {len(rejected)}{_R}")
    if approved:
        print(f"    {_M}Adapted (scaled) : {len(adapted)}{_R}  "
              f"({len(approved)-len(adapted)} at full target risk)")

    if rejected:
        print(f"\n{_B}  REJECTION BREAKDOWN{_R}")
        for reason, cnt in sorted(reject_counts.items(), key=lambda x: -x[1]):
            print(f"    {_Y}{cnt:>3}×{_R}  {reason}")

    # ── Approved detail ─────────────────────────────────────────────────────
    if approved:
        sl_src = defaultdict(int)
        for r in approved:
            sl_src[r.get("sl_source", "ATR")] += 1

        print(f"\n{_B}  APPROVED — AVERAGES{_R}")
        print(f"    SL source → ATR:{sl_src['ATR']}  OB:{sl_src['OB']}")
        print(f"    Avg ATR              : {avg(approved,'atr'):.6f}")
        print(f"    Avg SL ATR dist      : {avg(approved,'sl_atr_dist'):.6f}")
        ob_rows = [r for r in approved if r.get("sl_ob_dist") not in ("","None",None)]
        if ob_rows:
            print(f"    Avg SL OB dist       : {avg(ob_rows,'sl_ob_dist'):.6f}")
        print(f"    Avg SL final dist    : {avg(approved,'sl_distance'):.6f}")
        print(f"    Avg R:R              : {avg(approved,'rr_ratio'):.2f}")
        print(f"    Avg quantity         : {avg(approved,'quantity'):.6f}")
        print(f"    Avg notional         : ${avg(approved,'notional'):,.2f}")
        print(f"    Avg margin           : ${avg(approved,'margin_used'):,.2f}  "
              f"({avg(approved,'margin_pct'):.1f}%)")
        print(f"    Avg target risk $    : ${avg(approved,'dollar_risk_target'):.2f}")
        print(f"    Avg actual risk $    : ${avg(approved,'dollar_risk_actual'):.2f}")
        if adapted:
            print(f"    Avg reduction factor : {avg(adapted,'reduction_factor'):.4f}  "
                  f"(adapted trades only)")
        print(f"    Avg net profit       : ${avg(approved,'net_profit'):.4f}")

        print(f"\n{_B}  APPROVED TRADES (per-trade detail){_R}")
        header = (
            f"  {'Sym':<10} {'Sig':<6} {'Entry':>11} "
            f"{'SL_ATRd':>9} {'SL_OBd':>9} {'SL_fd':>9} {'Src':<4} "
            f"{'Qty':>9} {'Notional':>11} {'Mgn%':>5} "
            f"{'Trgt$':>7} {'Real$':>7} {'RF':>6} {'NetP':>8}"
        )
        print(header)
        print("  " + "─" * (len(header) - 2))

        for r in approved:
            col = _G if r.get("signal") == "LONG" else _RD
            rf  = flt(r, "reduction_factor")
            rf_col = _Y if rf < 1.0 else _GR
            ob_d = r.get("sl_ob_dist", "")
            ob_d_str = f"{flt(r,'sl_ob_dist'):>9.5f}" if ob_d not in ("","None",None) else f"{'N/A':>9}"
            net = flt(r, "net_profit")
            net_col = _G if net >= 0 else _RD
            print(
                f"  {col}{r.get('symbol',''):<10} {r.get('signal',''):<6}{_R}"
                f"{flt(r,'entry_price'):>11.4f} "
                f"{flt(r,'sl_atr_dist'):>9.5f} "
                f"{ob_d_str} "
                f"{flt(r,'sl_distance'):>9.5f} "
                f"{r.get('sl_source','ATR'):<4} "
                f"{flt(r,'quantity'):>9.5f} "
                f"${flt(r,'notional'):>10,.2f} "
                f"{flt(r,'margin_pct'):>5.1f}% "
                f"${flt(r,'dollar_risk_target'):>6.2f} "
                f"${flt(r,'dollar_risk_actual'):>6.2f} "
                f"{rf_col}{rf:>6.4f}{_R} "
                f"{net_col}${net:>7.4f}{_R}"
            )

    print(f"\n{'='*72}\n")


def main() -> None:
    n_cycles = int(sys.argv[1]) if len(sys.argv) > 1 else 5

    print(f"{'='*62}")
    print(f"  TEST RUN — {n_cycles} cycles, no sleep, ADAPTIVE SIZING ON")
    print(f"{'='*62}")

    client    = build_client()
    positions: dict = {}

    for cycle in range(1, n_cycles + 1):
        if positions:
            log_open_positions(positions)
            positions = update_open_positions(client, positions)
        run_cycle(client, positions, cycle)

    print_stats(n_cycles)


if __name__ == "__main__":
    main()
