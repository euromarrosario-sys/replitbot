"""
main.py — Binance Futures paper-trading bot (order-book primary)

Cycle logic (per symbol, per scan):
  1. Fetch order book  →  PRIMARY signal (LONG / SHORT / NEUTRAL)
  2. If actionable: fetch indicators → apply EMA / RSI filter
  3. If filter passes: calculate position sizing + net profit
  4. Net profit gate: reject if profit after fees/slippage < MIN_NET_PROFIT_USD
  5. Approved trades open a paper position (no real orders sent)

Between cycles (open positions):
  6. Fetch current price for each open position
  7. Update trailing stop (activates only once past breakeven)
  8. Close position if SL or TP hit → log realised P&L
"""

import time
import os
from binance.client import Client

from config import (
    API_KEY, API_SECRET, API_KEY_REAL, API_SECRET_REAL, TESTNET, MODE,
    SYMBOLS, SCAN_INTERVAL_SECONDS,
    MIN_NET_PROFIT_USD, TRAILING_STOP_PCT,
    MAX_OPEN_POSITIONS, MAX_DAILY_LOSS, MAX_RISK_PER_TRADE,
)
from alert_engine        import AlertEngine
from alert_manager       import AlertManager
from risk_engine         import RiskEngine
from execution_engine    import ExecutionEngine
from signal_generator    import SignalGenerator
from symbol_scanner      import SymbolScanner
from data_provider       import DataProvider
from binance_test_client  import BinanceTestClient
from runtime_controller   import RuntimeController
from orderbook_analyzer import analyze_orderbook
from market_scanner     import get_indicator_data, check_indicator_filter
from risk_manager       import (
    calculate_position, is_trade_allowed,
    update_trailing_stop, check_position_exit,
)
from trade_logger import (
    log_ob_scan, log_scan_header, log_scan_footer,
    log_trade_decision, log_trailing_activated, log_trailing_update,
    log_position_close, log_open_positions,
    log_error, log_info,
)


# ── Client ─────────────────────────────────────────────────────────────────

def build_client():
    if MODE == "REAL":
        key    = API_KEY_REAL
        secret = API_SECRET_REAL
        if not key or not secret:
            raise EnvironmentError(
                "REAL mode requires BINANCE_API_KEY_REAL and "
                "BINANCE_API_SECRET_REAL to be set as environment variables."
            )
        client = Client(key, secret)
    else:
        key    = API_KEY
        secret = API_SECRET
        if not key or not secret:
            raise EnvironmentError(
                "PAPER mode requires BINANCE_API_KEY and "
                "BINANCE_API_SECRET (testnet keys from testnet.binancefuture.com)."
            )
        # BinanceTestClient pins FUTURES_URL to the testnet endpoint —
        # more reliable than testnet=True alone in python-binance.
        client = BinanceTestClient(key, secret)

    try:
        client.futures_ping()
        server_time = client.futures_time()
        futures_url = getattr(getattr(client, "client", client), "FUTURES_URL", "unknown")
        log_info(
            f"Connected to Binance Futures {'Testnet' if TESTNET else 'Mainnet'} "
            f"[MODE={MODE}] — server time: {server_time['serverTime']}"
        )
        print("FUTURES_URL:", futures_url)
    except Exception as exc:
        hint = (
            "Check keys at testnet.binancefuture.com"
            if MODE != "REAL" else
            "Check keys at binance.com → API Management"
        )
        raise ConnectionError(f"Futures unreachable: {exc}\n{hint}") from exc

    return client


# ── Position management ────────────────────────────────────────────────────

def _current_price(client: Client, symbol: str) -> float | None:
    try:
        ticker = client.futures_symbol_ticker(symbol=symbol)
        return float(ticker["price"])
    except Exception as exc:
        log_error(symbol, f"Price fetch failed: {exc}")
        return None


def update_open_positions(client: Client, positions: dict, risk_multiplier: float = 1.0) -> dict:
    """
    For every open paper position:
      • Fetch current price
      • Update trailing stop (activates only after breakeven)
      • Close position if SL or TP is reached
    Returns the updated positions dict (closed entries are removed).
    """
    to_close = []

    for symbol, pos in positions.items():
        price = _current_price(client, symbol)
        if price is None:
            continue

        old_sl    = pos["stop_loss"]
        trail_pct = (TRAILING_STOP_PCT / 100) * risk_multiplier
        pos, just_activated = update_trailing_stop(pos, price, trail_pct_override=trail_pct)

        if just_activated:
            log_trailing_activated(
                symbol, pos["signal"], pos["breakeven_price"],
                price, pos["stop_loss"]
            )
        elif pos.get("trailing_active") and pos["stop_loss"] != old_sl:
            log_trailing_update(
                symbol, pos["signal"], old_sl, pos["stop_loss"],
                pos["extreme_price"]
            )

        should_exit, reason = check_position_exit(pos, price)
        if should_exit:
            log_position_close(pos, price, reason)
            to_close.append(symbol)

    for sym in to_close:
        del positions[sym]

    return positions


# ── Main scan cycle ────────────────────────────────────────────────────────

def run_cycle(
    positions: dict,
    cycle: int,
    symbol_scanner,
    data_provider,
    signal_generator,
    exec_engine,
    usdt_pairs: list[str],
) -> None:
    """
    One full scan-decide-execute cycle.
        1. SymbolScanner picks the best candidate from usdt_pairs.
        2. DataProvider fetches + filters market data for that symbol.
        3. SignalGenerator scores and produces LONG / SHORT / NO_TRADE.
        4. ExecutionEngine opens the position when action != NO_TRADE.
    Modifies `positions` in-place.
    """
    log_scan_header(cycle)

    # ── 1. Pick best symbol ───────────────────────────────────────────────
    if len(positions) >= MAX_OPEN_POSITIONS:
        log_info(
            f"[CYCLE] MAX_OPEN_POSITIONS={MAX_OPEN_POSITIONS} reached — skipping scan"
        )
        log_scan_footer(0, 0, 0, 0)
        return

    tradeable = [s for s in usdt_pairs if s not in positions]
    if not tradeable:
        log_info("[CYCLE] All symbols have open positions — skipping scan")
        log_scan_footer(0, 0, 0, 0)
        return

    symbol, score = symbol_scanner.scan(tradeable)
    if symbol is None:
        log_info("[CYCLE] No scoreable symbol found this cycle")
        log_scan_footer(0, 0, 0, 0)
        return

    log_info(f"[CYCLE] Best candidate: {symbol}  scanner_score={score:+.4f}")

    print("CYCLE START")
    print("symbol:", symbol)

    # ── 2. Fetch market data ──────────────────────────────────────────────
    market_data = data_provider.get(symbol)
    if market_data is None:
        log_info(f"[CYCLE] {symbol} filtered out by DataProvider")
        log_scan_footer(0, 0, 0, 0)
        return

    print("market_data OK")

    # ── 3. Generate signal ────────────────────────────────────────────────
    signal = signal_generator.generate(market_data)

    print("signal:", signal)
    print("score:", signal.get("score"))
    print("confidence:", signal.get("confidence"))
    print("risk_multiplier:", exec_engine.risk_engine.multiplier)

    # ── 4. Execute ────────────────────────────────────────────────────────
    if signal["action"] != "NO_TRADE":
        print(">>> EXECUTION GATE PASSED")
        paper_pos = exec_engine.execute_signal(
            signal = signal,
            symbol = symbol,
            price  = signal["entry_price"],
        )
        if paper_pos:
            positions[symbol] = paper_pos

    action = signal["action"]
    log_scan_footer(
        1 if action == "LONG" else 0,
        1 if action == "SHORT" else 0,
        1 if action == "NO_TRADE" else 0,
        0,
    )


# ── Bot ────────────────────────────────────────────────────────────────────

class Bot:
    def __init__(self):
        self.client        = build_client()
        self.positions     = {}
        self.cycle         = 0
        self.ctrl          = RuntimeController()
        self.alert_engine  = AlertEngine()
        self.alert_manager = AlertManager()
        self.risk_engine   = RiskEngine()
        self.exec_engine   = ExecutionEngine(self.client, self.risk_engine)
        self.sig_generator = SignalGenerator()
        self.sym_scanner   = SymbolScanner(self.client)
        self.data_provider = DataProvider(self.client)

    # ── Banner ────────────────────────────────────────────────────────────

    @staticmethod
    def _banner() -> None:
        mode_label = "REAL (MAINNET)" if MODE == "REAL" else "PAPER (TESTNET)"
        print("=" * 62)
        print(f"  Binance Futures Bot  —  ORDER BOOK PRIMARY  —  {mode_label}")
        print(f"  Symbols : {', '.join(SYMBOLS)}")
        print(f"  Leverage: 5×   Min net profit: ${MIN_NET_PROFIT_USD}")
        print(f"  Interval: {SCAN_INTERVAL_SECONDS}s")
        print(f"  Risk cap: {MAX_RISK_PER_TRADE:.1%}/trade   "
              f"Daily limit: {MAX_DAILY_LOSS:.1%}   "
              f"Max positions: {MAX_OPEN_POSITIONS}")
        print("=" * 62)

    # ── Status ────────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "trading":        self.trading_enabled,
            "risk":           self.risk_engine.multiplier,
            "open_positions": self.execution_engine.get_open_positions(),
            "daily_pnl":      self.risk_engine.daily_pnl,
            "symbol":         self.sym_scanner.current_symbol,
        }

    # ── Property alias ────────────────────────────────────────────────────

    @property
    def execution_engine(self):
        return self.exec_engine

    # ── Pause / Resume ────────────────────────────────────────────────────

    def pause(self) -> None:
        self.trading_enabled = False
        log_info("[BOT] paused — trading_enabled=False")

    def resume(self) -> None:
        self.trading_enabled = True
        log_info("[BOT] resumed — trading_enabled=True")

    # ── Kill switch ───────────────────────────────────────────────────────

    def kill_switch(self) -> None:
        """
        Hard stop: disable trading, set emergency_stop, close all positions.
        The main loop will print 'EMERGENCY STOP ACTIVE' and exit on the
        next iteration.
        """
        log_info("[BOT] KILL SWITCH ACTIVATED")
        self.trading_enabled = False
        self.emergency_stop  = True
        self.execution_engine.close_all_positions(self.positions)

    # ── Properties (delegate to RuntimeController) ───────────────────────

    @property
    def emergency_stop(self) -> bool:
        return self.ctrl.emergency_stop

    @emergency_stop.setter
    def emergency_stop(self, value: bool) -> None:
        self.ctrl.emergency_stop = value

    @property
    def trading_enabled(self) -> bool:
        return self.ctrl.trading_enabled

    @trading_enabled.setter
    def trading_enabled(self, value: bool) -> None:
        self.ctrl.trading_enabled = value

    # ── Cycle body ────────────────────────────────────────────────────────

    def run_cycle(self) -> None:
        """One full bot cycle: position management → risk pipeline → entry scan."""
        self.cycle += 1
        print("trading_enabled:", self.trading_enabled)
        print("open_positions:", len(self.positions))
        try:
            account   = self.client.futures_account()
            available = float(account["availableBalance"])
            print("available balance:", available)
            # Update open positions (trailing stops, exits)
            if self.positions:
                log_open_positions(self.positions)
                self.positions = update_open_positions(
                    self.client,
                    self.positions,
                    risk_multiplier=self.risk_engine.multiplier,
                )

            # Risk pipeline: alerts → risk engine
            alerts       = self.alert_engine.get_alerts(window=5)
            signals_risk = self.alert_manager.process(alerts)
            self.risk_engine.apply(signals_risk)
            self.risk_engine.recover()

            # Entry gates (checked in order)
            if self.risk_engine.disable_trading:
                log_info(
                    f"[BOT] MAX_DAILY_LOSS={MAX_DAILY_LOSS:.1%} reached — "
                    "no new trades this cycle"
                )
            else:
                run_cycle(
                    positions        = self.positions,
                    cycle            = self.cycle,
                    symbol_scanner   = self.sym_scanner,
                    data_provider    = self.data_provider,
                    signal_generator = self.sig_generator,
                    exec_engine      = self.exec_engine,
                    usdt_pairs       = SYMBOLS,
                )

        except Exception as exc:
            log_error("BOT", str(exc))

        # Keep ExecutionEngine in sync so get_open_positions() is current
        self.exec_engine._positions = self.positions

        log_info(f"Sleeping {SCAN_INTERVAL_SECONDS}s…\n")
        time.sleep(SCAN_INTERVAL_SECONDS)

    # ── Main loop ─────────────────────────────────────────────────────────

    def start(self) -> None:
        self._banner()

        while True:
            if self.emergency_stop:
                print("EMERGENCY STOP ACTIVE")
                break

            if not self.trading_enabled:
                time.sleep(1)
                continue

            try:
                self.run_cycle()
            except KeyboardInterrupt:
                print("\n  Bot stopped by user.")
                break


if __name__ == "__main__":
    print("BOT STARTING IN REAL MODE...")
    bot = Bot()
    bot.start()
