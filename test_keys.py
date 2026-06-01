"""
test_keys.py — diagnostica directamente si las keys del testnet funcionan.
Bypassa python-binance y hace la llamada con requests + HMAC propio.

Uso: python3 test_keys.py
"""

import os
import time
import hmac
import hashlib
import requests

API_KEY    = os.environ.get("BINANCE_API_KEY", "")
API_SECRET = os.environ.get("BINANCE_API_SECRET", "")

BASE = "https://testnet.binancefuture.com"

def sign(params: str) -> str:
    return hmac.new(
        API_SECRET.encode(),
        params.encode(),
        hashlib.sha256,
    ).hexdigest()

def test_ping():
    r = requests.get(f"{BASE}/fapi/v1/ping")
    print("ping:", r.status_code, r.json())

def test_time():
    r = requests.get(f"{BASE}/fapi/v1/time")
    print("serverTime:", r.json().get("serverTime"))

def test_account(path="/fapi/v2/account"):
    ts     = int(time.time() * 1000)
    params = f"timestamp={ts}"
    sig    = sign(params)
    url    = f"{BASE}{path}?{params}&signature={sig}"
    r = requests.get(url, headers={"X-MBX-APIKEY": API_KEY})
    data = r.json()
    if "code" in data:
        print(f"{path} → {r.status_code} ERROR: {data}")
    else:
        print(f"{path} → {r.status_code} OK  availableBalance={data.get('availableBalance','N/A')}")

def test_balance():
    ts     = int(time.time() * 1000)
    params = f"timestamp={ts}"
    sig    = sign(params)
    url    = f"{BASE}/fapi/v2/balance?{params}&signature={sig}"
    r = requests.get(url, headers={"X-MBX-APIKEY": API_KEY})
    data = r.json()
    if isinstance(data, dict) and "code" in data:
        print(f"balance → {r.status_code} ERROR: {data}")
    else:
        usdt = next((x for x in data if x.get("asset") == "USDT"), None)
        print(f"balance → {r.status_code} OK  USDT availableBalance={usdt.get('availableBalance') if usdt else 'N/A'}")

if __name__ == "__main__":
    print(f"KEY prefix: {API_KEY[:8]}..." if API_KEY else "KEY: (empty)")
    print()
    test_ping()
    test_time()
    test_account("/fapi/v1/account")
    test_account("/fapi/v2/account")
    test_account("/fapi/v3/account")
    test_balance()
