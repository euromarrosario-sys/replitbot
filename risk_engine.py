"""
risk_engine.py

Tracks a live risk multiplier (1.0 = normal, < 1.0 = reduced).
AlertManager signals of action="REDUCE_RISK" drive the multiplier down.
Each cycle without a new signal it recovers by RECOVERY_STEP toward 1.0.
"""

from config import RISK_PER_TRADE_PCT, MAX_DAILY_LOSS
from trade_logger import log_info


class RiskEngine:
    MIN_MULTIPLIER  = 0.25   # floor: never below 25% of base risk
    RECOVERY_STEP   = 0.05   # +5% per cycle when no active alert

    def __init__(self):
        self._multiplier:       float = 1.0
        self._daily_loss:       float = 0.0    # cumulative realised loss fraction today
        self._trading_disabled: bool  = False  # latched True when MAX_DAILY_LOSS is hit
        self.realized_pnl:      float = 0.0    # cumulative realised PnL (USDT)
        self.growth_multiplier: float = 1.0    # position-sizing growth factor

    # ── Public ───────────────────────────────────────────────────────────────

    @property
    def risk_pct(self) -> float:
        """Effective RISK_PER_TRADE_PCT after applying the current multiplier."""
        return round(RISK_PER_TRADE_PCT * self._multiplier, 6)

    def get_risk(self) -> float:
        """Callable alias for risk_pct — used by ExecutionEngine."""
        return self.risk_pct

    @property
    def multiplier(self) -> float:
        return self._multiplier

    def get_multiplier(self) -> float:
        """Callable alias for the multiplier property."""
        return self._multiplier

    def update_pnl(self, pnl: float) -> None:
        """
        Record a closed-trade PnL (USDT) and adjust the growth multiplier.

        realized_pnl > $10  → 2.0×  (scale up aggressively)
        realized_pnl > $5   → 1.5×  (scale up moderately)
        realized_pnl < $0   → 1.0×  (reset to base on net loss)
        """
        self.realized_pnl += pnl

        if self.realized_pnl > 10:
            self.growth_multiplier = 2.0
        elif self.realized_pnl > 5:
            self.growth_multiplier = 1.5
        elif self.realized_pnl < 0:
            self.growth_multiplier = 1.0

    def get_growth_multiplier(self) -> float:
        """
        Position-sizing growth factor (starts at 1.0).
        Independent from the risk multiplier — updated via realized_pnl.
        """
        return self.growth_multiplier

    def apply(self, signals: list[dict]) -> None:
        """
        Reduce the risk multiplier for every REDUCE_RISK signal.
        Reduction magnitude scales with signal confidence:
            new_multiplier = current × (1 − confidence × 0.5)
        Floor is capped at MIN_MULTIPLIER.
        """
        for s in signals:
            if s.get("action") != "REDUCE_RISK":
                continue
            conf      = float(s.get("confidence", 0.5))
            reduction = 1.0 - conf * 0.5
            before    = self._multiplier
            self._multiplier = max(
                self.MIN_MULTIPLIER,
                self._multiplier * reduction,
            )
            log_info(
                f"[RISK] multiplier {before:.2f} → {self._multiplier:.2f}  "
                f"(confidence={conf}  effective_risk_pct={self.risk_pct:.4f}%)"
            )

    # ── Daily loss tracking ───────────────────────────────────────────────────

    @property
    def daily_loss_pct(self) -> float:
        """Cumulative realised loss as a fraction of balance today (e.g. 0.015 = 1.5%)."""
        return self._daily_loss

    @property
    def daily_pnl(self) -> float:
        """Net daily PnL as a signed fraction (losses are negative, e.g. -0.015 = -1.5%)."""
        return -self._daily_loss

    @property
    def disable_trading(self) -> bool:
        """True once daily loss >= MAX_DAILY_LOSS. Latches until reset_daily()."""
        return self._trading_disabled

    def record_loss(self, loss_fraction: float) -> None:
        """
        Call after a losing trade closes.
        loss_fraction: positive decimal representing the loss (e.g. 0.005 = 0.5%).
        Latches disable_trading when MAX_DAILY_LOSS is breached.
        """
        self._daily_loss += abs(loss_fraction)
        log_info(
            f"[RISK] daily loss updated: {self._daily_loss:.4f}  "
            f"(limit={MAX_DAILY_LOSS})"
        )
        if self._daily_loss >= MAX_DAILY_LOSS:
            self._trading_disabled = True
            log_info("[RISK] MAX_DAILY_LOSS reached — disable_trading=True")

    def reset_daily(self) -> None:
        """Reset daily loss counter and re-enable trading (call each morning)."""
        self._daily_loss       = 0.0
        self._trading_disabled = False
        log_info("[RISK] daily loss counter reset — trading re-enabled")

    def recover(self) -> None:
        """
        Increment multiplier toward 1.0 by RECOVERY_STEP.
        Call once per cycle before apply() so recovery is gradual.
        """
        if self._multiplier < 1.0:
            before           = self._multiplier
            self._multiplier = min(1.0, self._multiplier + self.RECOVERY_STEP)
            log_info(
                f"[RISK] recovering: {before:.2f} → {self._multiplier:.2f}  "
                f"(effective_risk_pct={self.risk_pct:.4f}%)"
            )
