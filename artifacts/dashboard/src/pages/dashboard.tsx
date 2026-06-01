import { useState, useEffect, useRef, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  useGetSummary,
  useGetPositions,
  useGetSymbolStats,
  useGetSizing,
  useGetPnlCurve,
  useGetTrades,
  useGetSummaryBlocks,
} from "@workspace/api-client-react";
import {
  AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  LineChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  RefreshCw, Sun, Moon, TrendingUp, TrendingDown,
  ChevronDown, Check, Download,
} from "lucide-react";
import { CSVLink } from "react-csv";

// ── Constants ───────────────────────────────────────────────────────────────
const CHART_COLORS = {
  blue:   "#0079F2",
  purple: "#795EFF",
  green:  "#009118",
  red:    "#c0392b",
  pink:   "#ec4899",
  yellow: "#d4a017",
};

const SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT"];

const INTERVAL_OPTIONS = [
  { label: "Each 5 min",  ms: 5  * 60 * 1000 },
  { label: "Each 15 min", ms: 15 * 60 * 1000 },
  { label: "Each 1 h",   ms: 60 * 60 * 1000 },
];

// ── Formatters ───────────────────────────────────────────────────────────────
function fmt$(v: number | null | undefined, decimals = 2): string {
  if (v == null) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency", currency: "USD",
    minimumFractionDigits: decimals, maximumFractionDigits: decimals,
  }).format(v);
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return "—";
  return (v * 100).toFixed(1) + "%";
}

function fmtTs(ts: string): string {
  if (!ts) return "—";
  try {
    const d = new Date(ts);
    return d.toLocaleString("en-GB", {
      day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
    });
  } catch { return ts; }
}

function fmtNum(v: number | null | undefined, d = 4): string {
  if (v == null) return "—";
  return v.toFixed(d);
}

// ── Tooltip ──────────────────────────────────────────────────────────────────
function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: "#fff", borderRadius: 6, padding: "10px 14px",
      border: "1px solid #e0e0e0", color: "#1a1a1a", fontSize: 13,
    }}>
      <div style={{ marginBottom: 6, fontWeight: 500 }}>{label}</div>
      {payload.map((e: any, i: number) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 3 }}>
          <span style={{
            display: "inline-block", width: 10, height: 10,
            borderRadius: 2, background: e.color, flexShrink: 0,
          }} />
          <span style={{ color: "#444" }}>{e.name}</span>
          <span style={{ marginLeft: "auto", fontWeight: 600 }}>
            {typeof e.value === "number" ? fmt$(e.value, 2) : e.value}
          </span>
        </div>
      ))}
    </div>
  );
}

function CustomLegend({ payload }: any) {
  if (!payload?.length) return null;
  return (
    <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: "8px 16px", fontSize: 13 }}>
      {payload.map((e: any, i: number) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ display: "inline-block", width: 10, height: 10, borderRadius: 2, background: e.color }} />
          <span>{e.value}</span>
        </div>
      ))}
    </div>
  );
}

// ── KPI Card ─────────────────────────────────────────────────────────────────
function KpiCard({
  title, value, sub, color, loading, icon,
}: {
  title: string;
  value: string;
  sub?: string;
  color?: string;
  loading: boolean;
  icon?: React.ReactNode;
}) {
  return (
    <Card>
      <CardContent className="px-4 pt-4 pb-4">
        <div className="flex items-start justify-between">
          <p className="text-[13px] text-muted-foreground font-medium">{title}</p>
          {icon && <span className="text-muted-foreground">{icon}</span>}
        </div>
        {loading ? (
          <Skeleton className="mt-2 h-8 w-28" />
        ) : (
          <p className="mt-1 text-[26px] font-bold leading-tight" style={{ color: color ?? CHART_COLORS.blue }}>
            {value}
          </p>
        )}
        {sub && !loading && (
          <p className="mt-1 text-[12px] text-muted-foreground">{sub}</p>
        )}
      </CardContent>
    </Card>
  );
}

// ── Exit badge ───────────────────────────────────────────────────────────────
function ExitBadge({ type }: { type: string | null | undefined }) {
  if (!type) return <span className="text-muted-foreground text-xs">—</span>;
  const map: Record<string, string> = {
    TP: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
    SL: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
    TS: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  };
  return <span className={`px-2 py-0.5 rounded text-[11px] font-semibold ${map[type] ?? ""}`}>{type}</span>;
}

function SignalBadge({ sig }: { sig: string | null | undefined }) {
  if (!sig) return null;
  const cls = sig === "LONG"
    ? "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"
    : "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200";
  return <span className={`px-2 py-0.5 rounded text-[11px] font-semibold ${cls}`}>{sig}</span>;
}

// ── Main Dashboard ────────────────────────────────────────────────────────────
export default function Dashboard() {
  const queryClient = useQueryClient();

  const [isDark,       setIsDark]       = useState(false);
  const [autoRefresh,  setAutoRefresh]  = useState(false);
  const [isSpinning,   setIsSpinning]   = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [selectedMs,   setSelectedMs]   = useState(5 * 60 * 1000);
  const [lastRefreshed, setLastRefreshed] = useState<string | null>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Dark mode on <html>
  useEffect(() => {
    document.documentElement.classList.toggle("dark", isDark);
  }, [isDark]);

  // Click outside dropdown
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // Auto-refresh
  useEffect(() => {
    if (!autoRefresh) return;
    const id = setInterval(() => { queryClient.invalidateQueries(); }, selectedMs);
    return () => clearInterval(id);
  }, [autoRefresh, selectedMs, queryClient]);

  function handleRefresh() {
    setIsSpinning(true);
    queryClient.invalidateQueries().then(() => {
      setIsSpinning(false);
      setLastRefreshed(new Date().toLocaleTimeString("en-GB"));
    });
  }

  // ── Data hooks ──────────────────────────────────────────────────────────────
  const { data: summary,       isLoading: lSum }    = useGetSummary();
  const { data: positions,     isLoading: lPos }    = useGetPositions();
  const { data: symbolStats,   isLoading: lSym }    = useGetSymbolStats();
  const { data: sizing,        isLoading: lSiz }    = useGetSizing();
  const { data: pnlCurve,     isLoading: lPnl }    = useGetPnlCurve();
  const { data: trades,        isLoading: lTrd }    = useGetTrades();
  const { data: summaryBlocks, isLoading: lBlocks } = useGetSummaryBlocks();

  const loading = lSum || lPos || lSym || lSiz || lPnl || lTrd || lBlocks;

  // ── Derived ──────────────────────────────────────────────────────────────────
  const pnlPoints = useMemo(() => (pnlCurve ?? []).map((p, i) => ({
    ...p,
    label: `#${i + 1} ${p.symbol}`,
  })), [pnlCurve]);

  const exitPieData = useMemo(() => {
    if (!summary) return [];
    return [
      { name: "Take Profit", value: summary.exit_tp_count, color: CHART_COLORS.green },
      { name: "Trailing Stop", value: summary.exit_ts_count, color: CHART_COLORS.blue },
      { name: "Stop Loss", value: summary.exit_sl_count, color: CHART_COLORS.red },
    ].filter((d) => (d.value ?? 0) > 0);
  }, [summary]);

  const symbolBarData = useMemo(() => (symbolStats ?? []).map((s) => ({
    symbol: s.symbol.replace("USDT", ""),
    pnl:    s.total_net_pnl,
    trades: s.trades,
    wr:     parseFloat((s.win_rate * 100).toFixed(1)),
  })), [symbolStats]);

  const closedPositions = useMemo(() =>
    (positions ?? []).filter((p) => p.close_price != null),
  [positions]);

  const openPositions = useMemo(() =>
    (trades ?? []).filter((t) => t.allowed === "True").slice(0, 10),
  [trades]);

  const gridColor = isDark ? "rgba(255,255,255,0.07)" : "#e5e5e5";
  const tickColor = isDark ? "#98999C" : "#71717a";

  // ── Render ───────────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-background px-6 py-6">
      <div className="max-w-[1400px] mx-auto">

        {/* ── Header ── */}
        <div className="mb-6 flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
          <div className="pt-1">
            <div className="flex items-center gap-2">
              <span className="text-2xl">📈</span>
              <h1 className="font-bold text-[28px] tracking-tight">Futures Paper Trading Bot</h1>
            </div>
            <p className="text-muted-foreground mt-1 text-[14px]">
              Order-book · EMA/RSI · 5× leverage · Adaptive sizing · Paper balance $50,000
            </p>
            {lastRefreshed && (
              <p className="text-[12px] text-muted-foreground mt-2">Last refresh: {lastRefreshed}</p>
            )}
          </div>

          {/* Controls */}
          <div className="flex items-center gap-2 pt-1 print:hidden">
            {/* Split Refresh */}
            <div className="relative" ref={dropdownRef}>
              <div
                className="flex items-center rounded-[6px] overflow-hidden h-[28px] text-[12px]"
                style={{ backgroundColor: isDark ? "rgba(255,255,255,0.1)" : "#F0F1F2", color: isDark ? "#c8c9cc" : "#4b5563" }}
              >
                <button
                  onClick={handleRefresh}
                  disabled={loading}
                  className="flex items-center gap-1.5 px-2.5 h-full hover:bg-black/5 dark:hover:bg-white/10 transition-colors disabled:opacity-50"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${isSpinning ? "animate-spin" : ""}`} />
                  Refresh
                </button>
                <div className="w-px h-4 shrink-0" style={{ backgroundColor: isDark ? "rgba(255,255,255,0.15)" : "rgba(0,0,0,0.15)" }} />
                <button
                  onClick={() => setDropdownOpen((o) => !o)}
                  className="flex items-center justify-center px-1.5 h-full hover:bg-black/5 dark:hover:bg-white/10 transition-colors"
                >
                  <ChevronDown className="w-3.5 h-3.5" />
                </button>
              </div>

              {dropdownOpen && (
                <div
                  className="absolute right-0 top-full mt-1 z-50 rounded-[8px] p-3 min-w-[200px] shadow-lg border"
                  style={{ background: isDark ? "#1a2035" : "#fff", borderColor: isDark ? "#2a3550" : "#e5e7eb" }}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-[12px] font-medium">Auto-refresh</span>
                    <button
                      onClick={() => setAutoRefresh((v) => !v)}
                      className={`w-9 h-5 rounded-full transition-colors relative ${autoRefresh ? "bg-blue-500" : "bg-gray-300 dark:bg-gray-600"}`}
                    >
                      <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-all ${autoRefresh ? "left-4" : "left-0.5"}`} />
                    </button>
                  </div>
                  {INTERVAL_OPTIONS.map((opt) => (
                    <button
                      key={opt.ms}
                      onClick={() => { setSelectedMs(opt.ms); setDropdownOpen(false); }}
                      className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-[12px] hover:bg-black/5 dark:hover:bg-white/10 transition-colors"
                    >
                      <Check className={`w-3.5 h-3.5 ${selectedMs === opt.ms ? "opacity-100" : "opacity-0"}`} style={{ color: CHART_COLORS.blue }} />
                      {opt.label}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Dark mode */}
            <button
              onClick={() => setIsDark((d) => !d)}
              className="flex items-center justify-center w-[28px] h-[28px] rounded-[6px] transition-colors"
              style={{ backgroundColor: isDark ? "rgba(255,255,255,0.1)" : "#F0F1F2", color: isDark ? "#c8c9cc" : "#4b5563" }}
            >
              {isDark ? <Sun className="w-3.5 h-3.5" /> : <Moon className="w-3.5 h-3.5" />}
            </button>
          </div>
        </div>

        {/* ── KPI Row 1 — Balance & P&L ── */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
          <KpiCard
            loading={lSum}
            title="Saldo inicial"
            value={fmt$(summary?.paper_balance)}
            color={CHART_COLORS.blue}
          />
          <KpiCard
            loading={lSum}
            title="Saldo actual"
            value={fmt$(summary?.current_balance)}
            sub={summary ? `${summary.total_net_pnl >= 0 ? "+" : ""}${fmt$(summary.total_net_pnl)} neto` : undefined}
            color={summary && (summary.current_balance ?? 0) >= (summary.paper_balance ?? 0)
              ? CHART_COLORS.green : CHART_COLORS.red}
          />
          <KpiCard
            loading={lSum}
            title="P&L acumulado"
            value={summary ? `${summary.total_net_pnl >= 0 ? "+" : ""}${fmt$(summary.total_net_pnl)}` : "—"}
            color={summary && summary.total_net_pnl >= 0 ? CHART_COLORS.green : CHART_COLORS.red}
            icon={summary && summary.total_net_pnl >= 0
              ? <TrendingUp className="w-4 h-4" />
              : <TrendingDown className="w-4 h-4" />}
          />
          <KpiCard
            loading={lSum}
            title="Win Rate"
            value={fmtPct(summary?.win_rate)}
            sub={summary ? `${summary.win_count ?? 0}W / ${summary.loss_count ?? 0}L` : undefined}
            color={summary && (summary.win_rate ?? 0) >= 0.5 ? CHART_COLORS.green : CHART_COLORS.red}
          />
        </div>

        {/* ── KPI Row 2 — Stats ── */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
          <KpiCard
            loading={lSum}
            title="Beneficio promedio"
            value={fmt$(summary?.avg_win)}
            color={CHART_COLORS.green}
          />
          <KpiCard
            loading={lSum}
            title="Pérdida promedio"
            value={fmt$(summary?.avg_loss)}
            color={CHART_COLORS.red}
          />
          <KpiCard
            loading={lSum}
            title="Drawdown máximo"
            value={fmt$(summary?.max_drawdown)}
            color={CHART_COLORS.yellow}
          />
          <KpiCard
            loading={lSum}
            title="Operaciones cerradas"
            value={String(summary ? (summary.win_count ?? 0) + (summary.loss_count ?? 0) : 0)}
            sub={summary ? `Aprobadas: ${summary.trades_approved}` : undefined}
            color={CHART_COLORS.blue}
          />
        </div>

        {/* ── Exit breakdown KPIs ── */}
        <div className="grid grid-cols-3 gap-4 mb-4">
          <KpiCard
            loading={lSum}
            title="Take Profit (TP)"
            value={String(summary?.exit_tp_count ?? 0)}
            color={CHART_COLORS.green}
          />
          <KpiCard
            loading={lSum}
            title="Trailing Stop (TS)"
            value={String(summary?.exit_ts_count ?? 0)}
            color={CHART_COLORS.blue}
          />
          <KpiCard
            loading={lSum}
            title="Stop Loss (SL)"
            value={String(summary?.exit_sl_count ?? 0)}
            color={CHART_COLORS.red}
          />
        </div>

        {/* ── Charts Row ── */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">

          {/* Equity curve — 2/3 width */}
          <Card className="lg:col-span-2">
            <CardHeader className="px-4 pt-4 pb-2 flex-row items-center justify-between space-y-0">
              <CardTitle className="text-base">Curva de P&L acumulado</CardTitle>
              {!lPnl && (pnlCurve ?? []).length > 0 && (
                <CSVLink
                  data={pnlCurve ?? []}
                  filename="pnl-curve.csv"
                  className="print:hidden flex items-center justify-center w-[26px] h-[26px] rounded-[6px] transition-colors hover:opacity-80"
                  style={{ backgroundColor: isDark ? "rgba(255,255,255,0.1)" : "#F0F1F2", color: isDark ? "#c8c9cc" : "#4b5563" }}
                  aria-label="Export"
                >
                  <Download className="w-3.5 h-3.5" />
                </CSVLink>
              )}
            </CardHeader>
            <CardContent className="px-4 pb-4">
              {lPnl ? <Skeleton className="w-full h-[260px]" /> : (
                pnlPoints.length === 0
                  ? <EmptyChart height={260} msg="Sin operaciones cerradas aún" />
                  : (
                    <ResponsiveContainer width="100%" height={260} debounce={0}>
                      <AreaChart data={pnlPoints}>
                        <defs>
                          <linearGradient id="gradPnl" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor={CHART_COLORS.blue} stopOpacity={0.4} />
                            <stop offset="100%" stopColor={CHART_COLORS.blue} stopOpacity={0.03} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
                        <XAxis dataKey="label" tick={{ fontSize: 11, fill: tickColor }} stroke={tickColor} />
                        <YAxis tickFormatter={(v) => `$${v}`} tick={{ fontSize: 11, fill: tickColor }} stroke={tickColor} />
                        <Tooltip content={<CustomTooltip />} isAnimationActive={false} cursor={{ fill: "rgba(0,0,0,0.04)" }} />
                        <Area
                          dataKey="cumulative_net_pnl"
                          name="P&L acumulado"
                          stroke={CHART_COLORS.blue}
                          fill="url(#gradPnl)"
                          fillOpacity={1}
                          strokeWidth={2}
                          dot={false}
                          isAnimationActive={false}
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  )
              )}
            </CardContent>
          </Card>

          {/* Exit type pie — 1/3 width */}
          <Card>
            <CardHeader className="px-4 pt-4 pb-2 flex-row items-center justify-between space-y-0">
              <CardTitle className="text-base">Tipo de salida</CardTitle>
            </CardHeader>
            <CardContent className="px-4 pb-4">
              {lSum ? <Skeleton className="w-full h-[260px]" /> : (
                exitPieData.length === 0
                  ? <EmptyChart height={260} msg="Sin operaciones cerradas" />
                  : (
                    <ResponsiveContainer width="100%" height={260} debounce={0}>
                      <PieChart>
                        <Pie
                          data={exitPieData}
                          dataKey="value"
                          nameKey="name"
                          cx="50%" cy="45%"
                          outerRadius={90}
                          isAnimationActive={false}
                          label={({ name, value }) => `${name}: ${value}`}
                          labelLine={false}
                        >
                          {exitPieData.map((e, i) => (
                            <Cell key={i} fill={e.color ?? CHART_COLORS.blue} />
                          ))}
                        </Pie>
                        <Tooltip content={<CustomTooltip />} isAnimationActive={false} />
                        <Legend content={<CustomLegend />} />
                      </PieChart>
                    </ResponsiveContainer>
                  )
              )}
            </CardContent>
          </Card>
        </div>

        {/* ── Symbol Stats ── */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">

          {/* Symbol Bar Chart */}
          <Card>
            <CardHeader className="px-4 pt-4 pb-2 flex-row items-center justify-between space-y-0">
              <CardTitle className="text-base">P&L por símbolo</CardTitle>
              {!lSym && symbolBarData.length > 0 && (
                <CSVLink
                  data={symbolStats ?? []}
                  filename="symbol-stats.csv"
                  className="print:hidden flex items-center justify-center w-[26px] h-[26px] rounded-[6px] hover:opacity-80"
                  style={{ backgroundColor: isDark ? "rgba(255,255,255,0.1)" : "#F0F1F2", color: isDark ? "#c8c9cc" : "#4b5563" }}
                >
                  <Download className="w-3.5 h-3.5" />
                </CSVLink>
              )}
            </CardHeader>
            <CardContent className="px-4 pb-4">
              {lSym ? <Skeleton className="w-full h-[220px]" /> : (
                symbolBarData.every((d) => d.trades === 0)
                  ? <EmptyChart height={220} msg="Sin operaciones por símbolo" />
                  : (
                    <ResponsiveContainer width="100%" height={220} debounce={0}>
                      <BarChart data={symbolBarData} barSize={28}>
                        <CartesianGrid strokeDasharray="3 3" stroke={gridColor} vertical={false} />
                        <XAxis dataKey="symbol" tick={{ fontSize: 12, fill: tickColor }} stroke={tickColor} />
                        <YAxis tickFormatter={(v) => `$${v}`} tick={{ fontSize: 12, fill: tickColor }} stroke={tickColor} />
                        <Tooltip content={<CustomTooltip />} isAnimationActive={false} cursor={false} />
                        <Bar
                          dataKey="pnl"
                          name="P&L neto"
                          radius={[3, 3, 0, 0]}
                          fillOpacity={0.85}
                          isAnimationActive={false}
                        >
                          {symbolBarData.map((d, i) => (
                            <Cell key={i} fill={d.pnl >= 0 ? CHART_COLORS.green : CHART_COLORS.red} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  )
              )}
            </CardContent>
          </Card>

          {/* Symbol Table */}
          <Card>
            <CardHeader className="px-4 pt-4 pb-2 flex-row items-center justify-between space-y-0">
              <CardTitle className="text-base">Estadísticas por símbolo</CardTitle>
            </CardHeader>
            <CardContent className="px-4 pb-4">
              {lSym ? (
                <div className="space-y-2">
                  {SYMBOLS.map((s) => <Skeleton key={s} className="h-9 w-full" />)}
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Símbolo</TableHead>
                      <TableHead className="text-right">Ops</TableHead>
                      <TableHead className="text-right">Win %</TableHead>
                      <TableHead className="text-right">P&L neto</TableHead>
                      <TableHead className="text-right">P&L avg</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(symbolStats ?? []).map((s) => (
                      <TableRow key={s.symbol}>
                        <TableCell className="font-mono text-[13px] font-semibold">{s.symbol}</TableCell>
                        <TableCell className="text-right text-[13px]">{s.trades}</TableCell>
                        <TableCell className="text-right text-[13px]" style={{ color: s.win_rate >= 0.5 ? CHART_COLORS.green : s.trades > 0 ? CHART_COLORS.red : undefined }}>
                          {s.trades > 0 ? fmtPct(s.win_rate) : "—"}
                        </TableCell>
                        <TableCell className="text-right text-[13px]" style={{ color: s.total_net_pnl > 0 ? CHART_COLORS.green : s.total_net_pnl < 0 ? CHART_COLORS.red : undefined }}>
                          {s.trades > 0 ? `${s.total_net_pnl >= 0 ? "+" : ""}${fmt$(s.total_net_pnl)}` : "—"}
                        </TableCell>
                        <TableCell className="text-right text-[13px]">
                          {s.trades > 0 ? fmt$(s.avg_net_pnl) : "—"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </div>

        {/* ── Adaptive Sizing ── */}
        <Card className="mb-4">
          <CardHeader className="px-4 pt-4 pb-2 flex-row items-center justify-between space-y-0">
            <div>
              <CardTitle className="text-base">Sizing Adaptativo</CardTitle>
              <p className="text-[12px] text-muted-foreground mt-0.5">
                Ajustes aplicados cuando el margen objetivo supera el límite del 40%
              </p>
            </div>
            {!lSiz && (sizing ?? []).length > 0 && (
              <CSVLink
                data={sizing ?? []}
                filename="adaptive-sizing.csv"
                className="print:hidden flex items-center justify-center w-[26px] h-[26px] rounded-[6px] hover:opacity-80"
                style={{ backgroundColor: isDark ? "rgba(255,255,255,0.1)" : "#F0F1F2", color: isDark ? "#c8c9cc" : "#4b5563" }}
              >
                <Download className="w-3.5 h-3.5" />
              </CSVLink>
            )}
          </CardHeader>
          <CardContent className="px-4 pb-4">
            {lSiz ? (
              <div className="space-y-2">
                {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}
              </div>
            ) : (sizing ?? []).length === 0 ? (
              <p className="text-[13px] text-muted-foreground py-6 text-center">
                Sin operaciones aprobadas aún — los registros aparecerán aquí tras el primer trade.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Hora</TableHead>
                      <TableHead>Símbolo</TableHead>
                      <TableHead>Dir</TableHead>
                      <TableHead className="text-right">R. objetivo</TableHead>
                      <TableHead className="text-right">R. real</TableHead>
                      <TableHead className="text-right">Factor</TableHead>
                      <TableHead className="text-right">Margen</TableHead>
                      <TableHead className="text-right">Margen %</TableHead>
                      <TableHead>Motivo del ajuste</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(sizing ?? []).map((r, i) => (
                      <TableRow key={i}>
                        <TableCell className="text-[12px] whitespace-nowrap">{fmtTs(r.timestamp)}</TableCell>
                        <TableCell className="font-mono text-[12px] font-semibold">{r.symbol}</TableCell>
                        <TableCell><SignalBadge sig={r.signal} /></TableCell>
                        <TableCell className="text-right text-[12px]">{fmt$(r.dollar_risk_target)}</TableCell>
                        <TableCell className="text-right text-[12px]" style={{ color: (r.dollar_risk_actual ?? 0) < (r.dollar_risk_target ?? 0) ? CHART_COLORS.yellow : undefined }}>
                          {fmt$(r.dollar_risk_actual)}
                        </TableCell>
                        <TableCell className="text-right font-mono text-[12px]">
                          {r.reduction_factor != null ? r.reduction_factor.toFixed(4) : "—"}
                        </TableCell>
                        <TableCell className="text-right text-[12px]">{fmt$(r.margin_used, 0)}</TableCell>
                        <TableCell className="text-right text-[12px]">
                          {r.margin_pct != null ? r.margin_pct.toFixed(1) + "%" : "—"}
                        </TableCell>
                        <TableCell className="text-[11px] text-muted-foreground max-w-[280px]">
                          {r.adjustment_reason ?? "—"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>

        {/* ── Closed Positions ── */}
        <Card className="mb-4">
          <CardHeader className="px-4 pt-4 pb-2 flex-row items-center justify-between space-y-0">
            <div>
              <CardTitle className="text-base">Historial de operaciones cerradas</CardTitle>
              <p className="text-[12px] text-muted-foreground mt-0.5">{closedPositions.length} operación(es) cerradas</p>
            </div>
            {!lPos && closedPositions.length > 0 && (
              <CSVLink
                data={closedPositions}
                filename="closed-positions.csv"
                className="print:hidden flex items-center justify-center w-[26px] h-[26px] rounded-[6px] hover:opacity-80"
                style={{ backgroundColor: isDark ? "rgba(255,255,255,0.1)" : "#F0F1F2", color: isDark ? "#c8c9cc" : "#4b5563" }}
              >
                <Download className="w-3.5 h-3.5" />
              </CSVLink>
            )}
          </CardHeader>
          <CardContent className="px-4 pb-4">
            {lPos ? (
              <div className="space-y-2">
                {[...Array(5)].map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}
              </div>
            ) : closedPositions.length === 0 ? (
              <p className="text-[13px] text-muted-foreground py-6 text-center">
                Sin posiciones cerradas. Las operaciones aparecen aquí tras el cierre.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Hora</TableHead>
                      <TableHead>Símbolo</TableHead>
                      <TableHead>Dir</TableHead>
                      <TableHead className="text-right">Entrada</TableHead>
                      <TableHead className="text-right">Cierre</TableHead>
                      <TableHead className="text-right">P&L bruto</TableHead>
                      <TableHead className="text-right">P&L neto</TableHead>
                      <TableHead>Salida</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {closedPositions.map((p, i) => (
                      <TableRow key={i}>
                        <TableCell className="text-[12px] whitespace-nowrap">{fmtTs(p.timestamp)}</TableCell>
                        <TableCell className="font-mono text-[12px] font-semibold">{p.symbol}</TableCell>
                        <TableCell><SignalBadge sig={p.signal} /></TableCell>
                        <TableCell className="text-right text-[12px]">{fmtNum(p.entry_price, 4)}</TableCell>
                        <TableCell className="text-right text-[12px]">{fmtNum(p.close_price, 4)}</TableCell>
                        <TableCell className="text-right text-[12px]" style={{ color: (p.gross_pnl ?? 0) >= 0 ? CHART_COLORS.green : CHART_COLORS.red }}>
                          {p.gross_pnl != null ? `${p.gross_pnl >= 0 ? "+" : ""}${fmt$(p.gross_pnl)}` : "—"}
                        </TableCell>
                        <TableCell className="text-right text-[12px] font-semibold" style={{ color: (p.net_pnl ?? 0) >= 0 ? CHART_COLORS.green : CHART_COLORS.red }}>
                          {p.net_pnl != null ? `${p.net_pnl >= 0 ? "+" : ""}${fmt$(p.net_pnl)}` : "—"}
                        </TableCell>
                        <TableCell><ExitBadge type={p.exit_type} /></TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>

        {/* ── Recent Signals (approved trades info) ── */}
        <Card className="mb-4">
          <CardHeader className="px-4 pt-4 pb-2">
            <CardTitle className="text-base">Últimas señales aprobadas</CardTitle>
            <p className="text-[12px] text-muted-foreground mt-0.5">
              Operaciones aprobadas por el gestor de riesgo (en tiempo real)
            </p>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            {lTrd ? (
              <div className="space-y-2">
                {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}
              </div>
            ) : openPositions.length === 0 ? (
              <p className="text-[13px] text-muted-foreground py-6 text-center">
                Sin trades aprobados registrados aún.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Hora</TableHead>
                      <TableHead>Símbolo</TableHead>
                      <TableHead>Dir</TableHead>
                      <TableHead className="text-right">Entrada</TableHead>
                      <TableHead className="text-right">SL</TableHead>
                      <TableHead className="text-right">TP</TableHead>
                      <TableHead className="text-right">R:R</TableHead>
                      <TableHead className="text-right">Qty</TableHead>
                      <TableHead className="text-right">Margen</TableHead>
                      <TableHead className="text-right">P&L neto est.</TableHead>
                      <TableHead>SL fuente</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {openPositions.map((t, i) => (
                      <TableRow key={i}>
                        <TableCell className="text-[12px] whitespace-nowrap">{fmtTs(t.timestamp)}</TableCell>
                        <TableCell className="font-mono text-[12px] font-semibold">{t.symbol}</TableCell>
                        <TableCell><SignalBadge sig={t.signal} /></TableCell>
                        <TableCell className="text-right text-[12px]">{fmtNum(t.entry_price, 4)}</TableCell>
                        <TableCell className="text-right text-[12px]">{fmtNum(t.stop_loss, 4)}</TableCell>
                        <TableCell className="text-right text-[12px]">{fmtNum(t.take_profit, 4)}</TableCell>
                        <TableCell className="text-right text-[12px]">{t.rr_ratio?.toFixed(1)}</TableCell>
                        <TableCell className="text-right text-[12px]">{fmtNum(t.quantity, 3)}</TableCell>
                        <TableCell className="text-right text-[12px]">{fmt$(t.margin_used, 0)}</TableCell>
                        <TableCell className="text-right text-[12px]" style={{ color: (t.net_profit ?? 0) >= 0 ? CHART_COLORS.green : CHART_COLORS.red }}>
                          {t.net_profit != null ? `+${fmt$(t.net_profit)}` : "—"}
                        </TableCell>
                        <TableCell>
                          {t.sl_source && (
                            <Badge variant="outline" className="text-[10px]">{t.sl_source}</Badge>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>

        {/* ── Performance Stability ── */}
        <Card className="mb-4">
          <CardHeader className="px-4 pt-4 pb-2 flex-row items-center justify-between space-y-0">
            <div>
              <CardTitle className="text-base">Performance Stability</CardTitle>
              <p className="text-[12px] text-muted-foreground mt-0.5">
                Métricas agregadas por bloque de {100} ciclos · Generado con{" "}
                <code className="font-mono text-[11px]">run_extended_sim.py</code>
              </p>
            </div>
            {!lBlocks && (summaryBlocks ?? []).length > 0 && (
              <CSVLink
                data={summaryBlocks ?? []}
                filename="performance-stability.csv"
                className="print:hidden flex items-center justify-center w-[26px] h-[26px] rounded-[6px] hover:opacity-80"
                style={{ backgroundColor: isDark ? "rgba(255,255,255,0.1)" : "#F0F1F2", color: isDark ? "#c8c9cc" : "#4b5563" }}
              >
                <Download className="w-3.5 h-3.5" />
              </CSVLink>
            )}
          </CardHeader>
          <CardContent className="px-4 pb-4">
            {lBlocks ? (
              <div className="space-y-2">
                {[...Array(3)].map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}
              </div>
            ) : (summaryBlocks ?? []).length === 0 ? (
              <div className="py-8 text-center">
                <p className="text-[13px] text-muted-foreground">
                  Sin datos de simulación extendida todavía.
                </p>
                <p className="text-[12px] text-muted-foreground mt-1">
                  Ejecuta <code className="font-mono bg-muted px-1 rounded">python run_extended_sim.py 300</code> para generar bloques de rendimiento.
                </p>
              </div>
            ) : (
              <>
                {(() => {
                  const rows: SummaryRow[] = (summaryBlocks ?? []).map((b) => ({
                    block:                 b.block,
                    start_cycle:           b.start_cycle          ?? 0,
                    end_cycle:             b.end_cycle            ?? 0,
                    trades_closed:         b.trades_closed,
                    win_count:             b.win_count            ?? 0,
                    loss_count:            b.loss_count           ?? 0,
                    win_rate:              b.win_rate             ?? 0,
                    expectancy:            b.expectancy           ?? 0,
                    profit_factor:         b.profit_factor        ?? 0,
                    max_drawdown:          b.max_drawdown         ?? 0,
                    total_net_pnl:         b.total_net_pnl        ?? 0,
                    mark_to_market_closes: b.mark_to_market_closes ?? 0,
                  }));
                  const chartData = rows.map((b) => ({
                    block:        b.block,
                    winRate:      b.win_rate,
                    profitFactor: b.profit_factor,
                  }));
                  return (
                    <>
                      <StabilityAggregateBanner data={rows} isDark={isDark} />
                      <div className="mt-4">
                        <PerformanceStabilityChart data={chartData} />
                      </div>
                      <BlockTable data={rows} />
                    </>
                  );
                })()}
              </>
            )}
          </CardContent>
        </Card>

        {/* Footer */}
        <div className="text-center text-[11px] text-muted-foreground pb-4">
          Paper trading — sin dinero real · Leverage 5× · Binance Futures Testnet
        </div>

      </div>
    </div>
  );
}

// ── Performance Stability Chart ───────────────────────────────────────────────
function PerformanceStabilityChart({ data }: { data: { block: number; winRate: number; profitFactor: number }[] }) {
  return (
    <div style={{ width: "100%", height: 260 }}>
      <ResponsiveContainer>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="block" tickFormatter={(v) => `#${v}`} />
          <YAxis />
          <Tooltip
            formatter={(value: number, name: string) =>
              name === "Win Rate" ? fmtPct(value) : value.toFixed(2)
            }
            labelFormatter={(label) => `Bloque #${label}`}
          />
          <Legend />
          <Line
            type="monotone"
            dataKey="winRate"
            stroke={CHART_COLORS.green}
            strokeWidth={2}
            dot={{ r: 3 }}
            name="Win Rate"
          />
          <Line
            type="monotone"
            dataKey="profitFactor"
            stroke={CHART_COLORS.blue}
            strokeWidth={2}
            dot={{ r: 3 }}
            name="Profit Factor"
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Stability Aggregate Banner ────────────────────────────────────────────────
type SummaryRow = {
  block: number;
  start_cycle: number;
  end_cycle: number;
  trades_closed: number;
  win_count: number;
  loss_count: number;
  win_rate: number;
  expectancy: number;
  profit_factor: number;
  max_drawdown: number;
  total_net_pnl: number;
  mark_to_market_closes: number;
};

function detectDegradation(blocks: SummaryRow[]): boolean {
  if (blocks.length < 3) return false;
  const pf = blocks.map((b) => b.profit_factor);
  const avgPF = pf.reduce((a, b) => a + b, 0) / pf.length;
  const last  = pf[pf.length - 1];
  const prev  = pf[pf.length - 2];
  const prev2 = pf[pf.length - 3];
  const isDownTrend  = last < prev && prev < prev2;
  const belowAverage = last < avgPF;
  return isDownTrend && belowAverage;
}

function StabilityAggregateBanner({ data, isDark }: { data: SummaryRow[]; isDark: boolean }) {
  const active = data.filter((b) => b.trades_closed > 0);
  if (active.length === 0) return null;

  const avg = (arr: number[]) => arr.reduce((s, v) => s + v, 0) / arr.length;
  const avgWr   = avg(active.map((b) => b.win_rate));
  const avgExp  = avg(active.map((b) => b.expectancy));
  const validPf = active.filter((b) => b.profit_factor < 9999);
  const avgPf   = validPf.length > 0 ? avg(validPf.map((b) => b.profit_factor)) : 0;
  const maxDd   = Math.max(...active.map((b) => b.max_drawdown));
  const totalPnl = data.reduce((s, b) => s + b.total_net_pnl, 0);
  const degrading = detectDegradation(active);

  const cells = [
    { label: "Avg Win Rate",      value: fmtPct(avgWr),   color: avgWr  >= 0.5 ? CHART_COLORS.green : CHART_COLORS.red },
    { label: "Avg Expectancy",    value: `${avgExp >= 0 ? "+" : ""}${fmt$(avgExp, 2)}`, color: avgExp >= 0 ? CHART_COLORS.green : CHART_COLORS.red },
    { label: "Avg Profit Factor", value: avgPf.toFixed(2), color: avgPf  >= 1.0 ? CHART_COLORS.green : CHART_COLORS.red },
    { label: "Max Block DD",      value: fmt$(maxDd, 2),   color: CHART_COLORS.yellow },
    { label: "Total P&L",         value: `${totalPnl >= 0 ? "+" : ""}${fmt$(totalPnl, 2)}`, color: totalPnl >= 0 ? CHART_COLORS.green : CHART_COLORS.red },
    { label: "Blocks activos",    value: `${active.length} / ${data.length}`, color: CHART_COLORS.blue },
  ];

  return (
    <div className="space-y-2">
      {degrading && (
        <div
          className="flex items-center gap-2 rounded-md px-3 py-2 text-[12px] font-medium"
          style={{ backgroundColor: "rgba(239,68,68,0.12)", color: CHART_COLORS.red, border: `1px solid rgba(239,68,68,0.25)` }}
        >
          <TrendingDown className="w-3.5 h-3.5 shrink-0" />
          Degradación detectada — Profit Factor en caída sostenida los últimos 3 bloques y por debajo de la media
        </div>
      )}
      <div
        className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 rounded-lg p-3"
        style={{ backgroundColor: isDark ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.03)" }}
      >
        {cells.map((c) => (
          <div key={c.label} className="text-center">
            <p className="text-[11px] text-muted-foreground mb-0.5">{c.label}</p>
            <p className="text-[15px] font-bold" style={{ color: c.color }}>{c.value}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Block Table ───────────────────────────────────────────────────────────────
function BlockTable({ data }: { data: SummaryRow[] }) {
  return (
    <div className="mt-4 overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Bloque</TableHead>
            <TableHead>Ciclos</TableHead>
            <TableHead className="text-right">Trades</TableHead>
            <TableHead className="text-right">Win Rate</TableHead>
            <TableHead className="text-right">Expectancy</TableHead>
            <TableHead className="text-right">Profit Factor</TableHead>
            <TableHead className="text-right">Max DD</TableHead>
            <TableHead className="text-right">P&L bloque</TableHead>
            <TableHead className="text-right">MTM</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.map((b) => {
            const has = b.trades_closed > 0;
            const pfOk = b.profit_factor >= 1.0;
            const wrOk = b.win_rate      >= 0.5;
            const exOk = b.expectancy    >= 0;
            const pnlOk = b.total_net_pnl >= 0;
            return (
              <TableRow key={b.block} className={!has ? "opacity-50" : ""}>
                <TableCell className="font-semibold text-[13px]">#{b.block}</TableCell>
                <TableCell className="text-[12px] text-muted-foreground">{b.start_cycle}–{b.end_cycle}</TableCell>
                <TableCell className="text-right text-[13px]">
                  {has ? b.trades_closed : <span className="text-muted-foreground text-[11px]">0</span>}
                </TableCell>
                <TableCell className="text-right text-[13px] font-medium" style={{ color: has ? (wrOk ? CHART_COLORS.green : CHART_COLORS.red) : undefined }}>
                  {has ? fmtPct(b.win_rate) : "—"}
                </TableCell>
                <TableCell className="text-right text-[13px] font-medium" style={{ color: has ? (exOk ? CHART_COLORS.green : CHART_COLORS.red) : undefined }}>
                  {has ? `${exOk ? "+" : ""}${fmt$(b.expectancy, 2)}` : "—"}
                </TableCell>
                <TableCell className="text-right text-[13px] font-medium" style={{ color: has ? (pfOk ? CHART_COLORS.green : CHART_COLORS.red) : undefined }}>
                  {has ? b.profit_factor.toFixed(2) : "—"}
                </TableCell>
                <TableCell className="text-right text-[13px]" style={{ color: CHART_COLORS.yellow }}>
                  {has ? fmt$(b.max_drawdown, 2) : "—"}
                </TableCell>
                <TableCell className="text-right text-[13px] font-semibold" style={{ color: has ? (pnlOk ? CHART_COLORS.green : CHART_COLORS.red) : undefined }}>
                  {has ? `${pnlOk ? "+" : ""}${fmt$(b.total_net_pnl, 2)}` : "—"}
                </TableCell>
                <TableCell className="text-right text-[12px] text-muted-foreground">
                  {b.mark_to_market_closes}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

// ── Empty Chart ───────────────────────────────────────────────────────────────
function EmptyChart({ height, msg }: { height: number; msg: string }) {
  return (
    <div
      className="flex items-center justify-center text-[13px] text-muted-foreground"
      style={{ height }}
    >
      {msg}
    </div>
  );
}
