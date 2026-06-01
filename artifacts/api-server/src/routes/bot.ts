import { Router } from "express";
import fs from "fs";
import path from "path";
import { parse } from "csv-parse/sync";

const router = Router();

const LOGS_DIR = path.resolve(process.cwd(), "..", "..", "logs");
const PAPER_BALANCE = 50_000;

function readCsv(filename: string): Record<string, string>[] {
  const file = path.join(LOGS_DIR, filename);
  if (!fs.existsSync(file)) return [];
  const raw = fs.readFileSync(file, "utf8");
  if (!raw.trim()) return [];
  // Normalise mixed line-endings (\r\n → \n) before parsing
  const content = raw.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  try {
    return parse(content, { columns: true, skip_empty_lines: true });
  } catch {
    return [];
  }
}

function num(v: string | undefined): number | null {
  if (!v || v === "None" || v === "null") return null;
  const n = parseFloat(v);
  return isNaN(n) ? null : n;
}

function str(v: string | undefined): string | null {
  return v ?? null;
}

/** Classify exit_reason into TP / SL / TS */
function exitType(reason: string | undefined): string {
  if (!reason) return "SL";
  const r = reason.toLowerCase();
  if (r.includes("tp")) return "TP";
  if (r.includes("trail") || r.includes("ts")) return "TS";
  return "SL";
}

// GET /api/bot/signals
router.get("/signals", (req, res) => {
  const limit = Math.min(parseInt(String(req.query.limit ?? "100"), 10), 500);
  const rows = readCsv("signals.csv");
  const signals = rows.slice(-limit).reverse().map((r) => ({
    timestamp:               r.timestamp ?? "",
    symbol:                  r.symbol ?? "",
    ob_signal:               r.ob_signal ?? "",
    ob_confidence:           r.ob_confidence ?? "",
    bid_ask_ratio:           num(r.bid_ask_ratio),
    spread_pct:              num(r.spread_pct),
    bid_wall_conc:           num(r.bid_wall_conc),
    ask_wall_conc:           num(r.ask_wall_conc),
    indicator_filter_passed: str(r.indicator_filter_passed),
    filter_reason:           str(r.filter_reason),
    rsi:                     num(r.rsi),
    ema_fast:                num(r.ema_fast),
    ema_slow:                num(r.ema_slow),
    atr:                     num(r.atr),
    volume_ratio:            num(r.volume_ratio),
  }));
  res.json(signals);
});

// GET /api/bot/trades
router.get("/trades", (req, res) => {
  const limit = Math.min(parseInt(String(req.query.limit ?? "100"), 10), 500);
  const rows = readCsv("trades.csv");
  const trades = rows.slice(-limit).reverse().map((r) => ({
    timestamp:           r.timestamp ?? "",
    symbol:              r.symbol ?? "",
    signal:              str(r.signal),
    entry_price:         num(r.entry_price),
    stop_loss:           num(r.stop_loss),
    take_profit:         num(r.take_profit),
    rr_ratio:            num(r.rr_ratio),
    quantity:            num(r.quantity),
    notional:            num(r.notional),
    margin_used:         num(r.margin_used),
    margin_pct:          num(r.margin_pct),
    total_cost:          num(r.total_cost),
    gross_profit:        num(r.gross_profit),
    net_profit:          num(r.net_profit),
    dollar_risk_target:  num(r.dollar_risk_target),
    dollar_risk_actual:  num(r.dollar_risk_actual),
    reduction_factor:    num(r.reduction_factor),
    adjustment_reason:   str(r.adjustment_reason),
    sl_source:           str(r.sl_source),
    sl_atr_dist:         num(r.sl_atr_dist),
    sl_ob_dist:          num(r.sl_ob_dist),
    sl_distance:         num(r.sl_distance),
    atr:                 num(r.atr),
    ob_confidence:       str(r.ob_confidence),
    ob_imbalance:        str(r.ob_imbalance),
    allowed:             str(r.allowed),
    rejection_reason:    str(r.rejection_reason),
  }));
  res.json(trades);
});

// GET /api/bot/positions
router.get("/positions", (req, res) => {
  const rows = readCsv("positions.csv");
  const positions = rows.reverse().map((r) => ({
    timestamp:           r.timestamp ?? "",
    symbol:              r.symbol ?? "",
    signal:              r.signal ?? "",
    entry_price:         num(r.entry_price),
    close_price:         num(r.close_price),
    stop_loss_at_close:  num(r.stop_loss_at_close),
    take_profit:         num(r.take_profit),
    quantity:            num(r.quantity),
    gross_pnl:           num(r.gross_pnl),
    net_pnl:             num(r.net_pnl),
    total_cost:          num(r.total_cost),
    trailing_active:     str(r.trailing_active),
    exit_reason:         str(r.exit_reason),
    exit_type:           exitType(r.exit_reason),
  }));
  res.json(positions);
});

// GET /api/bot/summary
router.get("/summary", (req, res) => {
  const signals   = readCsv("signals.csv");
  const trades    = readCsv("trades.csv");
  const positions = readCsv("positions.csv");

  const long_signals    = signals.filter((r) => r.ob_signal === "LONG").length;
  const short_signals   = signals.filter((r) => r.ob_signal === "SHORT").length;
  const neutral_signals = signals.filter((r) => r.ob_signal === "NEUTRAL").length;

  const trades_approved = trades.filter((r) => r.allowed === "True").length;
  const trades_rejected = trades.filter((r) => r.allowed === "False").length;

  const closed = positions.map((r) => num(r.net_pnl)).filter((v): v is number => v !== null);
  const wins   = closed.filter((v) => v >= 0);
  const losses = closed.filter((v) => v < 0);

  const win_count  = wins.length;
  const loss_count = losses.length;
  const win_rate   = closed.length > 0 ? win_count / closed.length : 0;
  const avg_win    = wins.length   > 0 ? wins.reduce((s, v) => s + v, 0) / wins.length     : 0;
  const avg_loss   = losses.length > 0 ? losses.reduce((s, v) => s + v, 0) / losses.length : 0;

  const total_net_pnl   = closed.reduce((s, v) => s + v, 0);
  const total_gross_pnl = positions.reduce((s, r) => s + (num(r.gross_pnl) ?? 0), 0);

  // Max drawdown from equity curve
  let peak = 0, maxDrawdown = 0, running = 0;
  for (const p of [...positions].reverse()) {
    running += num(p.net_pnl) ?? 0;
    if (running > peak) peak = running;
    const dd = peak - running;
    if (dd > maxDrawdown) maxDrawdown = dd;
  }

  // Exit type breakdown
  const exit_tp_count = positions.filter((r) => exitType(r.exit_reason) === "TP").length;
  const exit_sl_count = positions.filter((r) => exitType(r.exit_reason) === "SL").length;
  const exit_ts_count = positions.filter((r) => exitType(r.exit_reason) === "TS").length;

  const rr_vals = trades
    .filter((r) => r.allowed === "True")
    .map((r) => num(r.rr_ratio))
    .filter((v): v is number => v !== null);
  const avg_rr = rr_vals.length > 0
    ? rr_vals.reduce((s, v) => s + v, 0) / rr_vals.length
    : 0;

  res.json({
    total_signals:          signals.length,
    long_signals,
    short_signals,
    neutral_signals,
    total_trades_evaluated: trades.length,
    trades_approved,
    trades_rejected,
    win_count,
    loss_count,
    win_rate:               parseFloat(win_rate.toFixed(4)),
    total_gross_pnl:        parseFloat(total_gross_pnl.toFixed(4)),
    total_net_pnl:          parseFloat(total_net_pnl.toFixed(4)),
    avg_win:                parseFloat(avg_win.toFixed(4)),
    avg_loss:               parseFloat(avg_loss.toFixed(4)),
    avg_rr:                 parseFloat(avg_rr.toFixed(2)),
    max_drawdown:           parseFloat(maxDrawdown.toFixed(4)),
    exit_tp_count,
    exit_sl_count,
    exit_ts_count,
    open_positions_count:   0,
    paper_balance:          PAPER_BALANCE,
    current_balance:        parseFloat((PAPER_BALANCE + total_net_pnl).toFixed(4)),
  });
});

// GET /api/bot/symbol-stats
router.get("/symbol-stats", (_req, res) => {
  const positions = readCsv("positions.csv");
  const SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT"];

  const stats = SYMBOLS.map((symbol) => {
    const rows = positions.filter((r) => r.symbol === symbol);
    const pnls = rows.map((r) => num(r.net_pnl)).filter((v): v is number => v !== null);
    const wins   = pnls.filter((v) => v >= 0);
    const losses = pnls.filter((v) => v < 0);
    const total  = pnls.reduce((s, v) => s + v, 0);
    return {
      symbol,
      trades:        rows.length,
      win_count:     wins.length,
      loss_count:    losses.length,
      win_rate:      rows.length > 0 ? parseFloat((wins.length / rows.length).toFixed(4)) : 0,
      total_net_pnl: parseFloat(total.toFixed(4)),
      avg_net_pnl:   rows.length > 0 ? parseFloat((total / rows.length).toFixed(4)) : 0,
    };
  });
  res.json(stats);
});

// GET /api/bot/sizing
router.get("/sizing", (req, res) => {
  const limit = Math.min(parseInt(String(req.query.limit ?? "100"), 10), 500);
  const rows = readCsv("trades.csv");
  const approved = rows.filter((r) => r.allowed === "True");
  const sizing = approved.slice(-limit).reverse().map((r) => ({
    timestamp:          r.timestamp ?? "",
    symbol:             r.symbol ?? "",
    signal:             str(r.signal),
    dollar_risk_target: num(r.dollar_risk_target),
    dollar_risk_actual: num(r.dollar_risk_actual),
    reduction_factor:   num(r.reduction_factor),
    margin_used:        num(r.margin_used),
    margin_pct:         num(r.margin_pct),
    adjustment_reason:  str(r.adjustment_reason),
    notional:           num(r.notional),
    net_profit:         num(r.net_profit),
  }));
  res.json(sizing);
});

// GET /api/bot/alerts
router.get("/alerts", (_req, res) => {
  const rows = readCsv("summary.csv");
  const blocks = rows
    .map((r) => ({
      block:         parseInt(r.block         ?? "0", 10),
      trades_closed: parseInt(r.trades_closed ?? "0", 10),
      profit_factor: parseFloat(r.profit_factor ?? "0") || 0,
    }))
    .filter((b) => b.trades_closed > 0);

  const alerts: Array<{
    type: string; severity: string; blockIds: number[];
    metric: string; values: number[]; triggered: boolean; confidence: number;
  }> = [];

  // DEGRADATION_TREND — Profit Factor falling 3+ consecutive blocks and below mean
  if (blocks.length >= 3) {
    const pf      = blocks.map((b) => b.profit_factor);
    const avgPF   = pf.reduce((a, v) => a + v, 0) / pf.length;
    const last    = pf[pf.length - 1];
    const prev    = pf[pf.length - 2];
    const prev2   = pf[pf.length - 3];
    const triggered = last < prev && prev < prev2 && last < avgPF;
    const win     = blocks.slice(-3);
    const winPf   = win.map((b) => b.profit_factor);

    // confidence: blend of (a) magnitude of total drop relative to window peak
    // and (b) slope consistency — how uniformly each step declined
    const peak      = Math.max(...winPf);
    const magnitude = peak > 0 ? Math.min(1, (peak - last) / peak) : 0;
    const drops     = winPf.slice(1).filter((v, i) => winPf[i] > v).length;
    const slopeConsistency = drops / (winPf.length - 1);            // 0–1
    const confidence = parseFloat((magnitude * 0.7 + slopeConsistency * 0.3).toFixed(2));

    alerts.push({
      type:       "DEGRADATION_TREND",
      severity:   triggered ? "high" : "low",
      blockIds:   win.map((b) => b.block),
      metric:     "profit_factor",
      values:     winPf,
      triggered,
      confidence,
    });
  }

  res.json({ timestamp: Math.floor(Date.now() / 1000), alerts });
});

// GET /api/bot/summary-blocks
router.get("/summary-blocks", (_req, res) => {
  const rows = readCsv("summary.csv");
  const blocks = rows.map((r) => ({
    block:                  parseInt(r.block ?? "0", 10),
    start_cycle:            parseInt(r.start_cycle ?? "0", 10),
    end_cycle:              parseInt(r.end_cycle ?? "0", 10),
    timestamp:              r.timestamp ?? "",
    trades_opened:          parseInt(r.trades_opened ?? "0", 10),
    trades_closed:          parseInt(r.trades_closed ?? "0", 10),
    win_count:              parseInt(r.win_count ?? "0", 10),
    loss_count:             parseInt(r.loss_count ?? "0", 10),
    win_rate:               num(r.win_rate) ?? 0,
    expectancy:             num(r.expectancy) ?? 0,
    profit_factor:          num(r.profit_factor) ?? 0,
    max_drawdown:           num(r.max_drawdown) ?? 0,
    total_net_pnl:          num(r.total_net_pnl) ?? 0,
    mark_to_market_closes:  parseInt(r.mark_to_market_closes ?? "0", 10),
  }));
  res.json(blocks);
});

// GET /api/bot/pnl-curve
router.get("/pnl-curve", (_req, res) => {
  const positions = readCsv("positions.csv");
  // chronological order for cumulative sum
  let cumulative = 0;
  const curve = [...positions].reverse().map((r) => {
    const pnl = num(r.net_pnl) ?? 0;
    cumulative += pnl;
    return {
      timestamp:          r.timestamp ?? "",
      symbol:             r.symbol ?? "",
      net_pnl:            parseFloat(pnl.toFixed(4)),
      cumulative_net_pnl: parseFloat(cumulative.toFixed(4)),
      exit_type:          exitType(r.exit_reason),
    };
  });
  res.json(curve);
});

export default router;
