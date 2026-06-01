"""
run_extended_sim.py

Extended simulation: runs N cycles in blocks of BLOCK_SIZE.
At the end of each block every open paper position is closed at the
current market price (mark-to-market) so that each block produces a
complete set of P&L data.  Block metrics are printed to the console
and appended to logs/summary.csv.

Usage:
    python run_extended_sim.py [total_cycles]   (default: 500)

The CSV log files (trades.csv, signals.csv, positions.csv, summary.csv)
are APPENDED, never cleared, so you can chain multiple runs.
"""

import sys
import os
import csv

import config
config.SCAN_INTERVAL_SECONDS = 0   # no sleep between cycles

from binance.client import Client
from main import build_client, run_cycle, update_open_positions, _current_price
from trade_logger import (
    log_summary_block, log_position_close, log_info, log_open_positions,
)
from config import BLOCK_SIZE, POSITIONS_CSV, SUMMARY_CSV

_R  = "\033[0m"
_G  = "\033[92m"
_RD = "\033[91m"
_Y  = "\033[93m"
_C  = "\033[96m"
_B  = "\033[1m"
_GR = "\033[90m"
_M  = "\033[95m"

DIVIDER = "═" * 72


def _load_positions_pnl_since(row_offset: int) -> list[float]:
    """
    Read net_pnl values from positions.csv starting at the given row offset.
    Used to capture natural closes that occurred during a block.
    """
    if not os.path.exists(POSITIONS_CSV):
        return []
    with open(POSITIONS_CSV, newline="") as f:
        rows = list(csv.DictReader(f))
    block_rows = rows[row_offset:]
    pnls = []
    for r in block_rows:
        v = r.get("net_pnl", "")
        if v not in ("", "None", None):
            try:
                pnls.append(float(v))
            except ValueError:
                pass
    return pnls


def _positions_csv_len() -> int:
    """Return number of data rows (excluding header) in positions.csv."""
    if not os.path.exists(POSITIONS_CSV):
        return 0
    with open(POSITIONS_CSV, newline="") as f:
        return max(0, sum(1 for _ in f) - 1)


def _mark_to_market(client: Client, positions: dict) -> list[float]:
    """
    Force-close all open paper positions at current market price.
    Writes each close to positions.csv via log_position_close.
    Returns list of net_pnl values for each forced close.
    """
    pnls = []
    for symbol, pos in list(positions.items()):
        price = _current_price(client, symbol)
        if price is None:
            log_info(f"[MTM] {symbol}: price unavailable, skipping mark-to-market")
            continue
        log_position_close(pos, price, "mark_to_market")
        # Recompute net_pnl locally (same formula as log_position_close)
        entry = pos["entry_price"]
        qty   = pos["quantity"]
        costs = pos.get("total_cost", 0)
        if pos["signal"] == "LONG":
            gross = (price - entry) * qty
        else:
            gross = (entry - price) * qty
        pnls.append(round(gross - costs, 6))
        del positions[symbol]
    return pnls


def run_extended_simulation(total_cycles: int = 500) -> None:
    n_blocks = max(1, total_cycles // BLOCK_SIZE)
    remainder = total_cycles % BLOCK_SIZE

    print(f"\n{DIVIDER}")
    print(f"{_B}{_C}  EXTENDED SIMULATION  —  {total_cycles} cycles  |  "
          f"{n_blocks} block(s) × {BLOCK_SIZE} cycles{_R}")
    print(f"  Block metrics saved to: {SUMMARY_CSV}")
    print(DIVIDER)

    client    = build_client()
    positions: dict = {}
    cycle     = 0
    block_num = 0

    def run_block(block_cycles: int) -> None:
        nonlocal cycle, block_num
        block_num  += 1
        start_cycle = cycle + 1
        trades_opened_this_block = 0
        pos_offset_start = _positions_csv_len()

        for _ in range(block_cycles):
            cycle += 1

            # Update open positions (natural SL/TP/TS exits)
            if positions:
                positions_before = set(positions.keys())
                update_open_positions(client, positions)
                positions_after = set(positions.keys())
                # Count natural closes (but their pnl will be read from CSV)
                _closed = positions_before - positions_after

            # Run scan (may open new positions — increments positions dict)
            prev_syms = set(positions.keys())
            run_cycle(client, positions, cycle)
            new_syms  = set(positions.keys()) - prev_syms
            trades_opened_this_block += len(new_syms)

        end_cycle = cycle

        # Natural closes during the block (from positions.csv)
        natural_pnls = _load_positions_pnl_since(pos_offset_start)

        # Mark-to-market: force-close all remaining open positions
        mtm_pnls = _mark_to_market(client, positions)

        all_pnls = natural_pnls + mtm_pnls

        log_summary_block(
            block          = block_num,
            start_cycle    = start_cycle,
            end_cycle      = end_cycle,
            trades_opened  = trades_opened_this_block,
            closed_pnls    = all_pnls,
            mark_to_market_closes = len(mtm_pnls),
        )

    # ── Run full blocks ───────────────────────────────────────────────────────
    for _ in range(n_blocks):
        run_block(BLOCK_SIZE)

    # ── Run partial remainder block (if any) ──────────────────────────────────
    if remainder > 0:
        print(f"\n  {_GR}Running remainder block: {remainder} cycle(s){_R}")
        run_block(remainder)

    # ── Final summary ─────────────────────────────────────────────────────────
    print(f"\n{DIVIDER}")
    print(f"{_B}{_C}  SIMULATION COMPLETE{_R}")
    print(f"  Total cycles   : {cycle}")
    print(f"  Blocks recorded: {block_num}")
    print(f"  Summary CSV    : {SUMMARY_CSV}")

    # Read back summary for aggregate view
    if os.path.exists(SUMMARY_CSV):
        with open(SUMMARY_CSV, newline="") as f:
            blocks = list(csv.DictReader(f))

        if blocks:
            def flt(r: dict, k: str) -> float:
                v = r.get(k, "")
                if v in ("", "None", None):
                    return 0.0
                try:
                    return float(v)
                except ValueError:
                    return 0.0

            total_trades  = sum(int(r.get("trades_closed", 0)) for r in blocks)
            all_wr        = [flt(r, "win_rate") for r in blocks if int(r.get("trades_closed", 0)) > 0]
            all_exp       = [flt(r, "expectancy") for r in blocks if int(r.get("trades_closed", 0)) > 0]
            all_pf        = [flt(r, "profit_factor") for r in blocks
                             if int(r.get("trades_closed", 0)) > 0 and flt(r, "profit_factor") < 9999]
            all_dd        = [flt(r, "max_drawdown") for r in blocks]
            all_pnl       = [flt(r, "total_net_pnl") for r in blocks]

            avg = lambda lst: sum(lst) / len(lst) if lst else 0.0

            print(f"\n{_B}  AGGREGATE ACROSS ALL BLOCKS{_R}")
            print(f"    Total trades closed : {total_trades}")
            print(f"    Avg win rate        : {avg(all_wr)*100:.1f}%")
            print(f"    Avg expectancy      : ${avg(all_exp):+.2f} / trade")
            print(f"    Avg profit factor   : {avg(all_pf):.2f}")
            print(f"    Max block drawdown  : ${max(all_dd):.2f}" if all_dd else "")
            print(f"    Total net P&L       : ${sum(all_pnl):+.2f}")
    print(DIVIDER)


if __name__ == "__main__":
    args = sys.argv[1:]

    # --no-filters  →  bypass EMA/RSI secondary filters for the simulation
    no_filters = "--no-filters" in args
    if no_filters:
        args = [a for a in args if a != "--no-filters"]
        config.USE_EMA_FILTER = False
        config.USE_RSI_FILTER = False
        print(f"\n{_Y}  [SIM] --no-filters active: EMA + RSI filters disabled{_R}")

    total = int(args[0]) if args else 500
    run_extended_simulation(total)
