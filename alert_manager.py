"""
alert_manager.py

Applies cooldown + severity filtering to Alert dicts (produced by
AlertEngine) and converts passing alerts into actionable signal dicts.
"""

import time


class AlertManager:
    def __init__(self):
        self.last_alerts: dict[str, float] = {}
        self.cooldown_sec: int = 300          # 5 min

    # ── public ───────────────────────────────────────────────────────────────

    def process(self, alerts: list[dict]) -> list[dict]:
        signals = []

        for alert in alerts:
            key = alert["type"]

            if self._is_on_cooldown(key):
                continue

            if alert["severity"] in ("high", "critical"):
                signals.append(self._to_signal(alert))

            self.last_alerts[key] = time.time()

        return signals

    # ── private ──────────────────────────────────────────────────────────────

    def _is_on_cooldown(self, key: str) -> bool:
        last = self.last_alerts.get(key)
        if last is None:
            return False
        return (time.time() - last) < self.cooldown_sec

    def _to_signal(self, alert: dict) -> dict:
        return {
            "action":     "REDUCE_RISK",
            "reason":     alert["type"],
            "confidence": alert.get("confidence", 0),
            "impact":     "position_sizing",
        }
