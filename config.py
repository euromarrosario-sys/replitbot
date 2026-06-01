import os

# ═══════════════════════════════════════════════════════════
# MODE  —  single switch between paper and live trading
#   "PAPER" → testnet endpoint + $50 000 paper balance
#   "REAL"  → mainnet endpoint + live account balance
# ═══════════════════════════════════════════════════════════
MODE = "PAPER"

# --- Binance API credentials ---
# PAPER mode  → testnet keys from testnet.binancefuture.com
API_KEY    = os.environ.get("BINANCE_API_KEY", "")
API_SECRET = os.environ.get("BINANCE_API_SECRET", "")

# REAL mode   → mainnet keys from binance.com
API_KEY_REAL    = os.environ.get("BINANCE_API_KEY_REAL", "")
API_SECRET_REAL = os.environ.get("BINANCE_API_SECRET_REAL", "")

# Derived from MODE — do not edit these directly
TESTNET           = MODE != "REAL"
PAPER_BALANCE_USD = 50_000.0 if MODE == "PAPER" else 0.0

# --- Symbols to scan ---
SYMBOLS = ["BTCUSDT"]

# --- Timeframe for secondary (indicator) analysis ---
KLINE_INTERVAL = "15m"
KLINE_LIMIT    = 100

# ═══════════════════════════════════════════════════════════
# ORDER BOOK  —  PRIMARY signal source
# ═══════════════════════════════════════════════════════════
ORDERBOOK_LIMIT = 20          # levels to fetch each side

# bid/ask ratio thresholds that define signal + confidence
OB_STRONG_LONG_RATIO    = 1.5   # ratio ≥ 1.5  → LONG  HIGH confidence
OB_MODERATE_LONG_RATIO  = 1.2   # ratio 1.2–1.5 → LONG  MODERATE
OB_MODERATE_SHORT_RATIO = 0.83  # ratio 0.67–0.83 → SHORT MODERATE
OB_STRONG_SHORT_RATIO   = 0.67  # ratio ≤ 0.67  → SHORT HIGH confidence

# Wall concentration: if top-3 levels hold > this fraction of total qty,
# a wall is considered "strong" and confidence upgrades to HIGH
OB_WALL_CONCENTRATION_THRESHOLD = 0.35

# ═══════════════════════════════════════════════════════════
# EMA / RSI  —  SECONDARY filters (set to False to bypass)
# ═══════════════════════════════════════════════════════════
USE_EMA_FILTER = True
USE_RSI_FILTER = True

RSI_OVERSOLD    = 35    # RSI below this blocks SHORT entries
RSI_OVERBOUGHT  = 65    # RSI above this blocks LONG  entries
EMA_FAST        = 9
EMA_SLOW        = 21
MIN_VOLUME_MULT = 1.3   # current vol must be ≥ 1.3× average (soft check)

# ═══════════════════════════════════════════════════════════
# RISK
# ═══════════════════════════════════════════════════════════
RISK_PER_TRADE_PCT  = 0.3    # % of account risked per trade (0.3% temporary)
MAX_RISK_PER_TRADE  = 0.005  # hard cap: max fraction of balance risked per trade (0.5%)
MAX_DAILY_LOSS      = 0.02   # halt trading when daily realised loss reaches 2% of balance
MAX_OPEN_POSITIONS  = 1      # maximum concurrent open positions
LEVERAGE            = 5      # futures leverage (keep at 5×)
REWARD_TO_RISK      = 2.0    # minimum TP:SL ratio
ATR_SL_MULTIPLIER  = 1.5   # SL = entry ± ATR × this  (minimum SL distance)
ATR_PERIOD         = 14
MAX_MARGIN_PCT     = 40.0  # max margin per trade as % of account balance

# ═══════════════════════════════════════════════════════════
# TRADING COSTS  (used in net-profit gate)
# ═══════════════════════════════════════════════════════════
TAKER_FEE_PCT     = 0.04   # Binance futures taker fee per side (%)
SLIPPAGE_PCT      = 0.05   # estimated slippage per side (%)
SAFETY_MARGIN_PCT = 0.10   # extra safety buffer per side (%)

# A trade is only approved if expected net profit (after all costs) ≥ this
MIN_NET_PROFIT_USD = 0.50

# ═══════════════════════════════════════════════════════════
# TRAILING STOP  (paper positions only)
# Activates ONLY once position is in real net profit
# ═══════════════════════════════════════════════════════════
TRAILING_STOP_PCT = 0.4    # trail 0.4% behind best price reached

# ═══════════════════════════════════════════════════════════
# BOT LOOP
# ═══════════════════════════════════════════════════════════
SCAN_INTERVAL_SECONDS = 60

# ═══════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════
LOG_DIR       = "logs"
TRADES_CSV    = f"{LOG_DIR}/trades.csv"
SIGNALS_CSV   = f"{LOG_DIR}/signals.csv"
POSITIONS_CSV = f"{LOG_DIR}/positions.csv"
SUMMARY_CSV   = f"{LOG_DIR}/summary.csv"

# ═══════════════════════════════════════════════════════════
# EXTENDED SIMULATION
# ═══════════════════════════════════════════════════════════
BLOCK_SIZE = 100   # cycles per block for aggregate statistics
