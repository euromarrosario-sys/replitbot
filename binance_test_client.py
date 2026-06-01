"""
binance_test_client.py

Thin wrapper around python-binance Client that pins the Futures endpoint
to the testnet URL.  The `testnet=True` flag in older python-binance
versions does not always redirect Futures traffic correctly — setting
FUTURES_URL explicitly is the reliable fix.

All attribute access is proxied to the inner Client so existing code that
calls client.futures_account_balance(), client.get_symbol_ticker(), etc.
works without modification.
"""

from binance.client import Client


TESTNET_FUTURES_URL = "https://testnet.binancefuture.com"


class BinanceTestClient:
    def __init__(self, api_key: str, api_secret: str):
        self.client = Client(api_key, api_secret, testnet=True, ping=False)
        self.client.FUTURES_URL = TESTNET_FUTURES_URL

    # ── Convenience methods ───────────────────────────────────────────────────

    def get_balance(self) -> list:
        """Return futures account balances for all assets."""
        return self.client.futures_account_balance()

    def create_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
    ) -> dict:
        """Place a futures order on the testnet."""
        return self.client.futures_create_order(
            symbol   = symbol,
            side     = side,
            type     = order_type,
            quantity = quantity,
        )

    # ── Transparent proxy ─────────────────────────────────────────────────────

    def __getattr__(self, name: str):
        """Forward any unknown attribute to the inner Client."""
        return getattr(self.client, name)

    def __repr__(self) -> str:
        return f"BinanceTestClient(futures_url={TESTNET_FUTURES_URL!r})"
