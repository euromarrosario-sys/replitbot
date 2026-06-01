"""
test_trade.py — fire a single hardcoded MARKET BUY to verify connectivity.

Usage:
    python3 test_trade.py
"""

from binance.client import Client
from config import API_KEY_REAL, API_SECRET_REAL

client = Client(API_KEY_REAL, API_SECRET_REAL)

account   = client.futures_account()
available = float(account["availableBalance"])
positions = client.futures_position_information(symbol="BTCUSDT")

print("available balance:", available)
print("open positions:", positions)
print(">>> ABOUT TO SEND ORDER")

order = client.create_order(
    symbol   = "BTCUSDT",
    side     = "BUY",
    type     = "MARKET",
    quantity = 0.001,
)

print("ORDER SENT:", order)
