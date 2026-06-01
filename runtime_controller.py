"""
runtime_controller.py

Runtime flags that can be toggled while the bot is running.

  trading_enabled  — False pauses new entries; open positions still managed
  emergency_stop   — True halts everything, including position management
"""

from trade_logger import log_info


class RuntimeController:
    def __init__(self):
        self.trading_enabled: bool = True
        self.emergency_stop:  bool = False

    # ── Controls ──────────────────────────────────────────────────────────────

    def pause(self) -> None:
        """Disable new entries. Open positions continue to be managed."""
        if self.trading_enabled:
            self.trading_enabled = False
            log_info("[CTRL] trading_enabled=False — new entries paused")

    def resume(self) -> None:
        """Re-enable new entries (has no effect if emergency_stop is active)."""
        if self.emergency_stop:
            log_info("[CTRL] resume() ignored — emergency_stop is active")
            return
        if not self.trading_enabled:
            self.trading_enabled = True
            log_info("[CTRL] trading_enabled=True — entries resumed")

    def trigger_emergency_stop(self) -> None:
        """
        Hard halt: disable trading AND block position management.
        Requires reset() to clear — intentionally manual.
        """
        self.trading_enabled = False
        self.emergency_stop  = True
        log_info("[CTRL] EMERGENCY STOP — all activity halted")

    def reset(self) -> None:
        """
        Clear emergency_stop and re-enable trading.
        Call only after manually verifying account state.
        """
        self.emergency_stop  = False
        self.trading_enabled = True
        log_info("[CTRL] reset — emergency_stop=False  trading_enabled=True")

    # ── Checks ────────────────────────────────────────────────────────────────

    def can_manage_positions(self) -> bool:
        """False only during emergency_stop — trailing stops and exits blocked."""
        return not self.emergency_stop

    def can_open_trades(self) -> bool:
        """False when paused OR emergency_stop is active."""
        return self.trading_enabled and not self.emergency_stop

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "trading_enabled": self.trading_enabled,
            "emergency_stop":  self.emergency_stop,
            "can_manage":      self.can_manage_positions(),
            "can_open":        self.can_open_trades(),
        }

    def __repr__(self) -> str:
        return (
            f"RuntimeController("
            f"trading_enabled={self.trading_enabled}, "
            f"emergency_stop={self.emergency_stop})"
        )
