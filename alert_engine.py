"""
alert_engine.py

Reads aggregate block history from summary.csv and produces Alert dicts
that match the /api/bot/alerts schema.  Window size is configurable so
callers can tune sensitivity: larger window = more stable mean baseline.
"""

import csv
import os

from config import SUMMARY_CSV


def _load_blocks(window: int) -> list[dict]:
    """Return the last `window` active blocks from summary.csv."""
    if not os.path.exists(SUMMARY_CSV):
        return []
    with open(SUMMARY_CSV, newline="") as f:
        rows = list(csv.DictReader(f))
    blocks = []
    for r in rows:
        try:
            tc = int(r.get("trades_closed", 0) or 0)
            blocks.append({
                "block":         int(r.get("block",         0) or 0),
                "trades_closed": tc,
                "profit_factor": float(r.get("profit_factor", 0) or 0),
            })
        except (ValueError, TypeError):
            continue
    active = [b for b in blocks if b["trades_closed"] > 0]
    return active[-window:]


def _build_alerts(blocks: list[dict]) -> list[dict]:
    """
    Compute alerts from a block window.  Requires at least 3 blocks.
    Degradation rule: last 3 blocks fall consecutively AND last < window mean.
    Confidence: blend of total-drop magnitude (70%) and slope consistency (30%).
    """
    if len(blocks) < 3:
        return []

    pf     = [b["profit_factor"] for b in blocks]
    avg_pf = sum(pf) / len(pf)

    last, prev, prev2 = pf[-1], pf[-2], pf[-3]
    triggered         = last < prev and prev < prev2 and last < avg_pf

    win    = blocks[-3:]
    win_pf = [b["profit_factor"] for b in win]
    peak   = max(win_pf) if max(win_pf) > 0 else 1
    mag    = min(1.0, (peak - last) / peak)
    drops  = sum(1 for i in range(1, len(win_pf)) if win_pf[i] < win_pf[i - 1])
    slope  = drops / (len(win_pf) - 1)

    return [{
        "type":       "DEGRADATION_TREND",
        "severity":   "high" if triggered else "low",
        "blockIds":   [b["block"] for b in win],
        "metric":     "profit_factor",
        "values":     win_pf,
        "triggered":  triggered,
        "confidence": round(mag * 0.7 + slope * 0.3, 2),
    }]


class AlertEngine:
    def __init__(self, default_window: int = 5):
        self.default_window = default_window

    def get_alerts(self, window: int | None = None) -> list[dict]:
        """
        Load the last `window` active blocks and return computed alerts.
        Falls back to `default_window` when window is not specified.
        """
        w      = window if window is not None else self.default_window
        blocks = _load_blocks(w)
        return _build_alerts(blocks)
