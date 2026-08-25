"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { ReportDateField, ReportFilters } from "@/lib/types";
import { resolvedLocalTimeZone, toLocalDateTimeInput } from "@/lib/date-time";
import {
  AlertTriangle, BarChart3, CheckCircle2, Clock, Download,
  Filter, RotateCcw, TicketIcon,
} from "lucide-react";
import {
  AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from "recharts";
import { cn } from "@/lib/utils";
import { Alert, Button, EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { PageFrame, PageHeader } from "@/components/layout/PageLayout";

const CHART_COLORS = ["#803CE8", "#005EB8", "#03CCB5", "#66FC90", "#E11BCC", "#F6AB3B", "#CF3E54"];
const REPORT_PRESETS: ReadonlyArray<readonly [number, string]> = [
  [1, "Last 24 hours"],
  [7, "Last 7 days"],
  [30, "Last 30 days"],
  [90, "Last 90 days"],
  [365, "Last 12 months"],
];

interface ReportFilterDraft {
  startLocal: string;
  endLocal: string;
  dateField: ReportDateField;
  status: string;
  priority: string;
  category: string;
}

function presetDraft(days: number): ReportFilterDraft {
  const end = new Date();
  end.setSeconds(0, 0);
  const start = new Date(end.getTime() - days * 24 * 60 * 60 * 1000);
  return {
    startLocal: toLocalDateTimeInput(start),
    endLocal: toLocalDateTimeInput(end),
    dateField: "created",
    status: "",
    priority: "",
    category: "",
  };
}

function filtersFromDraft(draft: ReportFilterDraft): ReportFilters | null {
  const start = new Date(draft.startLocal);
  const end = new Date(draft.endLocal);
  if (!draft.startLocal || !draft.endLocal || Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || start >= end) {
    return null;
  }
  return {
    startAt: start.toISOString(),
    endAt: end.toISOString(),
    dateField: draft.dateField,
    status: draft.status || undefined,
    priority: draft.priority || undefined,
    category: draft.category.trim() || undefined,
  };
}

function reportPeriodLabel(filters: ReportFilters) {
  const formatter = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
  return `${formatter.format(new Date(filters.startAt))} – ${formatter.format(new Date(filters.endAt))}`;
}

function reportFilterSignature(filters: ReportFilters | null) {
  if (!filters) return "";
  return [
    filters.startAt,
    filters.endAt,
    filters.dateField,
    filters.status ?? "",
    filters.priority ?? "",
    filters.category ?? "",
  ].join("\u0000");
}

function wrapChartLabel(value: unknown, maxCharacters = 18) {
  const words = String(value ?? "").trim().split(/\s+/).filter(Boolean);
  const chunks = words.flatMap((word) => {
    if (word.length <= maxCharacters) return [word];
    return Array.from({ length: Math.ceil(word.length / maxCharacters) }, (_, index) =>
      word.slice(index * maxCharacters, (index + 1) * maxCharacters)
    );
  });

  const lines = chunks.reduce<string[]>((result, chunk) => {
    const current = result.at(-1);
    if (!current || current.length + chunk.length + 1 > maxCharacters) result.push(chunk);
    else result[result.length - 1] = `${current} ${chunk}`;
    return result;
  }, []);

  return lines.length > 0 ? lines : [""];
}

function categoryChartHeight(data: Array<Record<string, unknown>>, key: string) {
  const labelRows = data.reduce((total, item) => total + wrapChartLabel(item[key]).length, 0);
  return Math.max(240, labelRows * 16 + data.length * 18 + 48);
}

function WrappedYAxisTick({ x = 0, y = 0, payload }: { x?: number; y?: number; payload?: { value?: unknown } }) {
  const lines = wrapChartLabel(payload?.value);
  const firstLineOffset = -((lines.length - 1) * 0.55);

  return (
    <g transform={`translate(${x},${y})`} aria-hidden="true">
      <text textAnchor="end" fill="#7E8691" fontSize={10}>
        {lines.map((line, index) => (
          <tspan key={`${line}-${index}`} x={-8} dy={index === 0 ? `${firstLineOffset}em` : "1.1em"}>{line}</tspan>
        ))}
      </text>
    </g>
  );
}

export default function ReportsPage() {
  const [draft, setDraft] = useState<ReportFilterDraft | null>(null);
  const [filters, setFilters] = useState<ReportFilters | null>(null);
  const [filterError, setFilterError] = useState("");
  const [exportError, setExportError] = useState("");
  const [exportNotice, setExportNotice] = useState("");
  const [exporting, setExporting] = useState(false);
  const [timeZone, setTimeZone] = useState("your local time zone");

  useEffect(() => {
    const initial = presetDraft(30);
    setDraft(initial);
    setFilters(filtersFromDraft(initial));
    setTimeZone(resolvedLocalTimeZone());
  }, []);

  const summaryQuery = useQuery({
    queryKey: ["report-summary", filters],
    queryFn: () => api.getReportSummary(filters!),
    enabled: Boolean(filters),
  });
  const volumeQuery = useQuery({
    queryKey: ["report-volume", filters],
    queryFn: () => api.getReportVolume(filters!),
    enabled: Boolean(filters),
  });
  const categoryQuery = useQuery({
    queryKey: ["report-by-category", filters],
    queryFn: () => api.getReportByCategory(filters!),
    enabled: Boolean(filters),
  });
  const statusQuery = useQuery({
    queryKey: ["report-by-status", filters],
    queryFn: () => api.getReportByStatus(filters!),
    enabled: Boolean(filters),
  });
  const slaQuery = useQuery({
    queryKey: ["report-sla", filters],
    queryFn: () => api.getReportSlaCompliance(filters!),
    enabled: Boolean(filters),
  });
  const resolutionQuery = useQuery({
    queryKey: ["report-resolution", filters],
    queryFn: () => api.getReportResolutionTime(filters!),
    enabled: Boolean(filters),
  });
  const statusesQuery = useQuery({ queryKey: ["status-config"], queryFn: api.getStatusConfig });
  const prioritiesQuery = useQuery({ queryKey: ["priority-config"], queryFn: api.getPriorityConfig });
  const categoriesQuery = useQuery({ queryKey: ["ticket-categories"], queryFn: api.getCategories });
  const queries = [summaryQuery, volumeQuery, categoryQuery, statusQuery, slaQuery, resolutionQuery];
  const summary = summaryQuery.data;
  const volume = volumeQuery.data;
  const byCategory = categoryQuery.data;
  const byStatus = statusQuery.data;
  const slaCompliance = slaQuery.data;
  const resolutionTime = resolutionQuery.data;
  const failed = queries.filter((query) => query.isError).length;

  const volumeData = (volume?.days || []).map((day, index) => ({ day, count: volume?.counts?.[index] ?? 0 }));
  const categoryData = (byCategory?.categories || []).map((c, i) => ({ name: c, value: byCategory?.counts?.[i] ?? 0 }));
  const statusData = (byStatus?.statuses || []).map((s, i) => ({ name: s, value: byStatus?.counts?.[i] ?? 0 }));
  const slaData = slaCompliance ? Object.entries(slaCompliance).map(([p, v]) => ({
    priority: p, compliance: v.compliance, breached: v.breached, total: v.total,
  })) : [];
  const resolutionData = (resolutionTime?.categories || []).map((c, i) => ({ category: c, hours: resolutionTime?.avg_hours?.[i] ?? 0 }));
  const draftFilters = draft ? filtersFromDraft(draft) : null;
  const hasUnappliedChanges = Boolean(
    filters && reportFilterSignature(draftFilters) !== reportFilterSignature(filters),
  );
  const appliedDimensions = filters ? [
    filters.status ? `Status: ${filters.status}` : "",
    filters.priority ? `Priority: ${filters.priority}` : "",
    filters.category ? `Category: ${filters.category}` : "",
  ].filter(Boolean) : [];

  const applyDraft = () => {
    if (!draft) return;
    const nextFilters = filtersFromDraft(draft);
    if (!nextFilters) {
      setFilterError("Choose a valid start and end time. The start must be before the end.");
      return;
    }
    setFilterError("");
    setExportError("");
    setExportNotice("");
    setFilters(nextFilters);
  };

  const applyPreset = (days: number) => {
    const nextDraft = {
      ...presetDraft(days),
      dateField: draft?.dateField ?? "created",
      status: draft?.status ?? "",
      priority: draft?.priority ?? "",
      category: draft?.category ?? "",
    } satisfies ReportFilterDraft;
    setDraft(nextDraft);
    setFilters(filtersFromDraft(nextDraft));
    setFilterError("");
    setExportError("");
    setExportNotice("");
  };

  const resetReport = () => {
    const nextDraft = presetDraft(30);
    setDraft(nextDraft);
    setFilters(filtersFromDraft(nextDraft));
    setFilterError("");
    setExportError("");
    setExportNotice("");
  };

  const exportCsv = async () => {
    if (!filters) return;
    setExporting(true);
    setExportError("");
    setExportNotice("");
    try {
      const result = await api.downloadReportCsv(filters);
      const url = URL.createObjectURL(result.blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = result.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
      setExportNotice(`Exported ${result.rowCount.toLocaleString()} matching ticket${result.rowCount === 1 ? "" : "s"}.`);
    } catch (error) {
      setExportError(error instanceof Error ? error.message : "The report could not be exported.");
    } finally {
      setExporting(false);
    }
  };

  return (
    <PageFrame width="wide">
      <PageHeader eyebrow="Operational analytics" icon={<BarChart3 className="h-4 w-4" />} title="Reports" description="Build a focused operational view, compare service outcomes, and export the matching ticket evidence." />

      <section className="card-surface space-y-5 p-4 sm:p-5" aria-labelledby="report-criteria-heading">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Filter className="h-4 w-4 text-semantic-primary" aria-hidden="true" />
              <h2 id="report-criteria-heading" className="text-sm font-semibold text-ink-700">Report criteria</h2>
            </div>
            <p className="mt-1 text-xs leading-5 text-ink-400">
              {filters
                ? `${filters.dateField === "created" ? "Created" : "Resolved"} between ${reportPeriodLabel(filters)}${appliedDimensions.length ? ` · ${appliedDimensions.join(" · ")}` : ""}${summary ? ` · ${summary.total_tickets.toLocaleString()} matching tickets` : ""}`
                : "Preparing the default 30-day reporting window…"}
            </p>
          </div>
          <Button
            variant="secondary"
            leadingIcon={<Download className="h-4 w-4" />}
            pending={exporting}
            pendingLabel="Exporting…"
            disabled={!filters || hasUnappliedChanges}
            onClick={() => void exportCsv()}
          >
            Export matching CSV
          </Button>
        </div>

        <div className="flex flex-wrap gap-2" aria-label="Quick date ranges">
          {REPORT_PRESETS.map(([days, label]) => (
            <Button key={days} size="sm" variant="ghost" onClick={() => applyPreset(days)}>{label}</Button>
          ))}
        </div>

        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <label>
            <span className="mb-1.5 block text-xs font-semibold text-ink-500">Time basis</span>
            <select
              className="input-base"
              value={draft?.dateField ?? "created"}
              disabled={!draft}
              onChange={(event) => setDraft((current) => current ? { ...current, dateField: event.target.value as ReportDateField } : current)}
            >
              <option value="created">Ticket created time</option>
              <option value="resolved">Ticket resolved time</option>
            </select>
          </label>
          <label>
            <span className="mb-1.5 block text-xs font-semibold text-ink-500">From</span>
            <input
              type="datetime-local"
              className="input-base"
              value={draft?.startLocal ?? ""}
              disabled={!draft}
              onChange={(event) => setDraft((current) => current ? { ...current, startLocal: event.target.value } : current)}
            />
          </label>
          <label>
            <span className="mb-1.5 block text-xs font-semibold text-ink-500">Through</span>
            <input
              type="datetime-local"
              className="input-base"
              value={draft?.endLocal ?? ""}
              disabled={!draft}
              onChange={(event) => setDraft((current) => current ? { ...current, endLocal: event.target.value } : current)}
            />
          </label>
          <label>
            <span className="mb-1.5 block text-xs font-semibold text-ink-500">Status</span>
            <select
              className="input-base"
              value={draft?.status ?? ""}
              disabled={!draft}
              onChange={(event) => setDraft((current) => current ? { ...current, status: event.target.value } : current)}
            >
              <option value="">All statuses</option>
              {(statusesQuery.data ?? []).map((item) => <option key={item.id} value={item.name}>{item.label}</option>)}
            </select>
          </label>
          <label>
            <span className="mb-1.5 block text-xs font-semibold text-ink-500">Priority</span>
            <select
              className="input-base"
              value={draft?.priority ?? ""}
              disabled={!draft}
              onChange={(event) => setDraft((current) => current ? { ...current, priority: event.target.value } : current)}
            >
              <option value="">All priorities</option>
              {(prioritiesQuery.data ?? []).map((item) => <option key={item.id} value={item.name}>{item.label}</option>)}
            </select>
          </label>
          <label>
            <span className="mb-1.5 block text-xs font-semibold text-ink-500">Category</span>
            <input
              className="input-base"
              list="report-category-options"
              value={draft?.category ?? ""}
              disabled={!draft}
              maxLength={100}
              placeholder="All categories"
              onChange={(event) => setDraft((current) => current ? { ...current, category: event.target.value } : current)}
            />
            <datalist id="report-category-options">
              {(categoriesQuery.data ?? []).map((item) => <option key={item.id} value={item.name} />)}
            </datalist>
          </label>
        </div>

        <div className="flex flex-col gap-3 border-t border-linen-300 pt-4 sm:flex-row sm:items-center sm:justify-between">
          <p className={cn("text-xs", hasUnappliedChanges ? "font-semibold text-semantic-warning" : "text-ink-400")}>
            {hasUnappliedChanges
              ? "Criteria have changed. Apply them before reviewing or exporting the new result."
              : `Times are entered in ${timeZone} and sent to the report service as UTC.`}
          </p>
          <div className="flex gap-2">
            <Button size="sm" variant="ghost" leadingIcon={<RotateCcw className="h-3.5 w-3.5" />} onClick={resetReport}>Reset</Button>
            <Button size="sm" onClick={applyDraft} disabled={!draft || !hasUnappliedChanges}>Apply criteria</Button>
          </div>
        </div>
      </section>

      {filterError && <Alert variant="danger" title="Check the report period">{filterError}</Alert>}
      {exportError && <Alert variant="danger" title="Export failed">{exportError}</Alert>}
      {exportNotice && <Alert variant="success" title="Export ready">{exportNotice}</Alert>}

      {failed === queries.length && (
        <ErrorState title="Reports could not be loaded" description="The analytics service did not return any report data." onRetry={() => void Promise.all(queries.map((query) => query.refetch()))} retrying={queries.some((query) => query.isFetching)} />
      )}
      {failed > 0 && failed < queries.length && <Alert variant="warning" title="Partial report data">{failed} report {failed === 1 ? "section is" : "sections are"} unavailable. Available figures remain visible and missing sections can be retried by refreshing the page.</Alert>}

      {/* KPI summary cards */}
      {failed < queries.length && <>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <KpiTile label="Matching tickets" value={summary?.total_tickets} icon={TicketIcon} loading={!filters || summaryQuery.isLoading} />
        <KpiTile label="Open" value={summary?.open_tickets} icon={Clock} color="text-semantic-info" loading={!filters || summaryQuery.isLoading} />
        <KpiTile label="Resolved" value={summary?.resolved_tickets} icon={CheckCircle2} color="text-semantic-success" loading={!filters || summaryQuery.isLoading} />
        <KpiTile label="SLA breached" value={summary?.breached_sla} icon={AlertTriangle} color="text-semantic-danger" loading={!filters || summaryQuery.isLoading} />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <MiniStat label="Avg resolution time" value={summary ? `${summary.avg_resolution_hours}h` : "—"} loading={!filters || summaryQuery.isLoading} />
        <MiniStat label="Escalation rate" value={summary ? `${summary.escalation_rate}%` : "—"} loading={!filters || summaryQuery.isLoading} />
        <MiniStat label="CSAT" value={summary ? `${summary.csat_proxy}%` : "—"} loading={!filters || summaryQuery.isLoading} />
      </div>

      {/* Volume chart */}
      <div className="card-surface min-w-0 p-4 sm:p-5">
        <h2 className="text-sm font-semibold text-ink-700 mb-4">Ticket volume by day</h2>
        {!filters || volumeQuery.isLoading ? <ChartSkeleton /> : volumeQuery.isError ? <SectionError onRetry={() => void volumeQuery.refetch()} /> : volumeData.length > 0 ? (
          <><p className="sr-only">Daily ticket volume for the selected period. Values range from {Math.min(...volumeData.map((item) => item.count))} to {Math.max(...volumeData.map((item) => item.count))} tickets per day.</p><ResponsiveContainer width="100%" height={240}>
            <AreaChart data={volumeData}>
              <defs>
                <linearGradient id="volGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#803CE8" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#803CE8" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#DDE2EA" vertical={false} />
              <XAxis dataKey="day" tick={{ fontSize: 10, fill: "#7E8691" }} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 10, fill: "#7E8691" }} allowDecimals={false} />
              <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #DDE2EA" }} />
              <Area type="monotone" dataKey="count" stroke="#803CE8" strokeWidth={2} fill="url(#volGrad)" isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer></>
        ) : (
          <EmptyChart />
        )}
      </div>

      <div className="grid min-w-0 grid-cols-1 items-start gap-6 lg:grid-cols-2">
        {/* By category */}
        <div className="card-surface min-w-0 p-4 sm:p-5">
          <h2 className="text-sm font-semibold text-ink-700 mb-4">Tickets by Category</h2>
          {!filters || categoryQuery.isLoading ? <ChartSkeleton /> : categoryQuery.isError ? <SectionError onRetry={() => void categoryQuery.refetch()} /> : categoryData.length > 0 ? (
            <div className="space-y-4">
              {byCategory?.truncated && <Alert variant="warning" title="Category view is limited" className="text-xs">Showing {categoryData.length.toLocaleString()} of {byCategory.total_categories.toLocaleString()} categories. Counts are exact for the categories shown.</Alert>}
              <ResponsiveContainer width="100%" height={210}>
                <PieChart>
                  <Pie data={categoryData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={78} innerRadius={40} isAnimationActive={false}>
                    {categoryData.map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
                  </Pie>
                  <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                </PieChart>
              </ResponsiveContainer>
              <ul className="grid min-w-0 gap-2 sm:grid-cols-2" aria-label="Ticket category legend">
                {categoryData.map((item, index) => (
                  <li key={`${item.name}-${index}`} className="flex min-w-0 items-start gap-2 rounded-lg bg-linen-100 px-3 py-2 text-xs">
                    <span className="mt-1 h-2.5 w-2.5 shrink-0 rounded-sm" style={{ backgroundColor: CHART_COLORS[index % CHART_COLORS.length] }} aria-hidden="true" />
                    <span className="min-w-0 flex-1 whitespace-normal break-words leading-5 text-ink-600 [overflow-wrap:anywhere]">{item.name}</span>
                    <span className="shrink-0 font-semibold tabular-nums text-ink-700">{item.value.toLocaleString()}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : <EmptyChart />}
        </div>

        {/* By status */}
        <div className="card-surface min-w-0 p-4 sm:p-5">
          <h2 className="text-sm font-semibold text-ink-700 mb-4">Tickets by Status</h2>
          {!filters || statusQuery.isLoading ? <ChartSkeleton /> : statusQuery.isError ? <SectionError onRetry={() => void statusQuery.refetch()} /> : statusData.length > 0 ? (
            <ResponsiveContainer width="100%" height={categoryChartHeight(statusData, "name")}>
              <BarChart data={statusData} layout="vertical" margin={{ left: 8, right: 16 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#DDE2EA" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 10, fill: "#7E8691" }} allowDecimals={false} />
                <YAxis type="category" dataKey="name" tick={<WrappedYAxisTick />} width={140} interval={0} />
                <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #DDE2EA" }} />
                <Bar dataKey="value" radius={[0, 4, 4, 0]} isAnimationActive={false}>
                  {statusData.map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : <EmptyChart />}
        </div>
      </div>

      {/* SLA compliance */}
      <div className="card-surface min-w-0 p-4 sm:p-5">
        <h2 className="text-sm font-semibold text-ink-700 mb-4">SLA Compliance by Priority</h2>
        {!filters || slaQuery.isLoading ? <ChartSkeleton /> : slaQuery.isError ? <SectionError onRetry={() => void slaQuery.refetch()} /> : slaData.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {slaData.map((s) => (
              <div key={s.priority} className="min-w-0 rounded border border-linen-400 p-4">
                <div className="mb-2 flex min-w-0 flex-wrap items-start justify-between gap-2">
                  <span className="min-w-0 whitespace-normal break-words text-sm font-semibold text-ink-700 [overflow-wrap:anywhere]">{s.priority}</span>
                  <span className={cn("shrink-0 text-lg font-bold", s.compliance >= 90 ? "text-moss-500" : s.compliance >= 70 ? "text-amber-500" : "text-rust-500")}>
                    {s.compliance}%
                  </span>
                </div>
                <div className="w-full bg-linen-300 rounded-full h-2 mb-2">
                  <div className={cn("h-2 rounded-full", s.compliance >= 90 ? "bg-moss-500" : s.compliance >= 70 ? "bg-amber-500" : "bg-rust-500")} style={{ width: `${s.compliance}%` }} />
                </div>
                <p className="text-xs text-ink-400">{s.breached} breached / {s.total} total</p>
              </div>
            ))}
          </div>
        ) : <EmptyChart />}
      </div>

      {/* Resolution time by category */}
      <div className="card-surface min-w-0 p-4 sm:p-5">
        <h2 className="text-sm font-semibold text-ink-700 mb-4">Avg Resolution Time by Category (hours)</h2>
        {!filters || resolutionQuery.isLoading ? <ChartSkeleton /> : resolutionQuery.isError ? <SectionError onRetry={() => void resolutionQuery.refetch()} /> : resolutionData.length > 0 ? (
          <div className="space-y-4">
            {resolutionTime?.truncated && <Alert variant="warning" title="Resolution averages are sampled" className="text-xs">Calculated from the latest {resolutionTime.analyzed_tickets.toLocaleString()} of {resolutionTime.total_matching_tickets.toLocaleString()} matching resolved tickets.</Alert>}
            <ResponsiveContainer width="100%" height={categoryChartHeight(resolutionData, "category")}>
              <BarChart data={resolutionData} layout="vertical" margin={{ left: 8, right: 16 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#DDE2EA" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 10, fill: "#7E8691" }} />
                <YAxis type="category" dataKey="category" tick={<WrappedYAxisTick />} width={140} interval={0} />
                <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #DDE2EA" }} />
                <Bar dataKey="hours" radius={[0, 4, 4, 0]} isAnimationActive={false}>
                  {resolutionData.map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : <EmptyChart />}
      </div>
      </>}
    </PageFrame>
  );
}

function KpiTile({ label, value, icon: Icon, color, loading }: { label: string; value?: number; icon: React.ElementType; color?: string; loading: boolean }) {
  return (
    <div className="card-surface p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-400">{label}</span>
        <Icon className={cn("w-4 h-4", color || "text-ink-400")} strokeWidth={1.5} />
      </div>
      {loading ? <Skeleton className="mt-3 h-8 w-20" /> : <p className="text-3xl font-semibold tracking-[-0.04em] text-ink-700 tabular-nums">{value == null ? "—" : value.toLocaleString()}</p>}
    </div>
  );
}

function MiniStat({ label, value, loading }: { label: string; value: string; loading: boolean }) {
  return (
    <div className="card-surface flex min-w-0 flex-wrap items-center justify-between gap-2 p-4">
      <span className="min-w-0 whitespace-normal break-words text-sm text-ink-500 [overflow-wrap:anywhere]">{label}</span>
      {loading ? <Skeleton className="h-6 w-16" /> : <span className="shrink-0 text-lg font-bold text-ink-700 tabular-nums">{value}</span>}
    </div>
  );
}

function EmptyChart() {
  return (
    <EmptyState className="min-h-[200px] border-0 bg-transparent" icon={<BarChart3 className="h-5 w-5" />} title="No data available" description="This report will populate when matching ticket activity exists." />
  );
}

function ChartSkeleton() { return <div className="space-y-4 py-3" aria-label="Loading report"><Skeleton className="h-44 w-full" /><Skeleton className="h-3 w-2/3" /></div>; }
function SectionError({ onRetry }: { onRetry: () => void }) { return <ErrorState className="min-h-[200px]" title="Report unavailable" description="This section could not be loaded." onRetry={onRetry} />; }
