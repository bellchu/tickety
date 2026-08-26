"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  ReportDateField,
  ReportFilters,
  ReportGroupBy,
  ReportMetric,
  ReportType,
} from "@/lib/types";
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

const REPORT_TYPES: Record<ReportType, { label: string; description: string; metric?: ReportMetric }> = {
  overview: {
    label: "Operational overview",
    description: "Key service metrics, volume, status, and category mix.",
  },
  volume: {
    label: "Ticket volume trend",
    description: "Ticket activity over time for demand and capacity planning.",
  },
  breakdown: {
    label: "Ticket breakdown",
    description: "Compare ticket counts across any operational dimension.",
    metric: "ticket_count",
  },
  resolution: {
    label: "Resolution performance",
    description: "Compare average resolution hours for resolved tickets.",
    metric: "avg_resolution_hours",
  },
  sla: {
    label: "SLA performance",
    description: "Compare active SLA compliance for tickets with tracked deadlines.",
    metric: "sla_compliance",
  },
};

const GROUP_OPTIONS: ReadonlyArray<readonly [ReportGroupBy, string]> = [
  ["status", "Status"],
  ["priority", "Priority"],
  ["category", "Category"],
  ["assignee", "Assignee"],
  ["source", "Source"],
  ["ticket_type", "Ticket type"],
];

type ChartStyle = "bar" | "donut";

interface ReportDraft {
  reportType: ReportType;
  groupBy: ReportGroupBy;
  chartStyle: ChartStyle;
  startLocal: string;
  endLocal: string;
  dateField: ReportDateField;
  status: string;
  priority: string;
  category: string;
  assigneeId: string;
  source: string;
  ticketType: string;
  resolutionState: string;
  slaState: string;
}

interface AppliedReport {
  type: ReportType;
  groupBy: ReportGroupBy;
  chartStyle: ChartStyle;
  filters: ReportFilters;
}

function presetDraft(days: number): ReportDraft {
  const end = new Date();
  end.setSeconds(0, 0);
  const start = new Date(end.getTime() - days * 24 * 60 * 60 * 1000);
  return {
    reportType: "overview",
    groupBy: "status",
    chartStyle: "bar",
    startLocal: toLocalDateTimeInput(start),
    endLocal: toLocalDateTimeInput(end),
    dateField: "created",
    status: "",
    priority: "",
    category: "",
    assigneeId: "",
    source: "",
    ticketType: "",
    resolutionState: "",
    slaState: "",
  };
}

function filtersFromDraft(draft: ReportDraft): ReportFilters | null {
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
    assigneeId: draft.assigneeId || undefined,
    source: draft.source || undefined,
    ticketType: draft.ticketType || undefined,
    resolutionState: draft.resolutionState as ReportFilters["resolutionState"] || undefined,
    slaState: draft.slaState as ReportFilters["slaState"] || undefined,
  };
}

function appliedReportFromDraft(draft: ReportDraft): AppliedReport | null {
  const filters = filtersFromDraft(draft);
  return filters ? { type: draft.reportType, groupBy: draft.groupBy, chartStyle: draft.chartStyle, filters } : null;
}

function reportPeriodLabel(filters: ReportFilters) {
  const formatter = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
  return `${formatter.format(new Date(filters.startAt))} – ${formatter.format(new Date(filters.endAt))}`;
}

function reportSignature(report: AppliedReport | null) {
  if (!report) return "";
  const filters = report.filters;
  return [
    report.type,
    report.groupBy,
    report.chartStyle,
    filters.startAt,
    filters.endAt,
    filters.dateField,
    filters.status ?? "",
    filters.priority ?? "",
    filters.category ?? "",
    filters.assigneeId ?? "",
    filters.source ?? "",
    filters.ticketType ?? "",
    filters.resolutionState ?? "",
    filters.slaState ?? "",
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

function titleCase(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export default function ReportsPage() {
  const [draft, setDraft] = useState<ReportDraft | null>(null);
  const [report, setReport] = useState<AppliedReport | null>(null);
  const [filterError, setFilterError] = useState("");
  const [exportError, setExportError] = useState("");
  const [exportNotice, setExportNotice] = useState("");
  const [exporting, setExporting] = useState(false);
  const [timeZone, setTimeZone] = useState("your local time zone");

  useEffect(() => {
    const initial = presetDraft(30);
    setDraft(initial);
    setReport(appliedReportFromDraft(initial));
    setTimeZone(resolvedLocalTimeZone());
  }, []);

  const filters = report?.filters ?? null;
  const showVolume = report?.type === "overview" || report?.type === "volume";
  const showOverviewBreakdowns = report?.type === "overview";
  const showSeries = report?.type === "breakdown" || report?.type === "resolution" || report?.type === "sla";
  const seriesMetric = report ? REPORT_TYPES[report.type].metric : undefined;

  const summaryQuery = useQuery({ queryKey: ["report-summary", filters], queryFn: () => api.getReportSummary(filters!), enabled: Boolean(filters) });
  const volumeQuery = useQuery({ queryKey: ["report-volume", filters], queryFn: () => api.getReportVolume(filters!), enabled: Boolean(filters && showVolume) });
  const categoryQuery = useQuery({ queryKey: ["report-by-category", filters], queryFn: () => api.getReportByCategory(filters!), enabled: Boolean(filters && showOverviewBreakdowns) });
  const statusQuery = useQuery({ queryKey: ["report-by-status", filters], queryFn: () => api.getReportByStatus(filters!), enabled: Boolean(filters && showOverviewBreakdowns) });
  const seriesQuery = useQuery({
    queryKey: ["report-series", filters, seriesMetric, report?.groupBy],
    queryFn: () => api.getReportSeries(filters!, seriesMetric!, report!.groupBy),
    enabled: Boolean(filters && showSeries && seriesMetric),
  });
  const optionsQuery = useQuery({ queryKey: ["report-options"], queryFn: api.getReportOptions });

  const activeQueries = [
    summaryQuery,
    ...(showVolume ? [volumeQuery] : []),
    ...(showOverviewBreakdowns ? [categoryQuery, statusQuery] : []),
    ...(showSeries ? [seriesQuery] : []),
  ];
  const failed = activeQueries.filter((query) => query.isError).length;
  const summary = summaryQuery.data;
  const volumeData = (volumeQuery.data?.days || []).map((day, index) => ({ day, count: volumeQuery.data?.counts?.[index] ?? 0 }));
  const categoryData = (categoryQuery.data?.categories || []).map((category, index) => ({ name: category, value: categoryQuery.data?.counts?.[index] ?? 0 }));
  const statusData = (statusQuery.data?.statuses || []).map((status, index) => ({ name: status, value: statusQuery.data?.counts?.[index] ?? 0 }));
  const seriesData = (seriesQuery.data?.labels || []).map((label, index) => ({
    name: label,
    value: seriesQuery.data?.values?.[index] ?? 0,
    count: seriesQuery.data?.counts?.[index] ?? 0,
  }));
  const draftReport = draft ? appliedReportFromDraft(draft) : null;
  const hasUnappliedChanges = Boolean(report && reportSignature(draftReport) !== reportSignature(report));
  const groupLabel = GROUP_OPTIONS.find(([value]) => value === report?.groupBy)?.[1] ?? "dimension";
  const appliedDimensions = filters ? [
    filters.status ? `Status: ${filters.status}` : "",
    filters.priority ? `Priority: ${filters.priority}` : "",
    filters.category ? `Category: ${filters.category}` : "",
    filters.assigneeId ? `Assignee: ${filters.assigneeId === "__unassigned__" ? "Unassigned" : optionsQuery.data?.assignees.find((item) => item.id === filters.assigneeId)?.name ?? filters.assigneeId}` : "",
    filters.source ? `Source: ${filters.source}` : "",
    filters.ticketType ? `Type: ${titleCase(filters.ticketType)}` : "",
    filters.resolutionState ? `State: ${titleCase(filters.resolutionState)}` : "",
    filters.slaState ? `SLA: ${titleCase(filters.slaState)}` : "",
  ].filter(Boolean) : [];
  const appliedCriteria = report && filters ? [
    `Period: ${reportPeriodLabel(filters)}`,
    `Time basis: ${filters.dateField === "created" ? "Created" : "Resolved"}`,
    ...appliedDimensions,
    ...(showSeries ? [`Grouped by: ${groupLabel}`] : []),
    ...(report.type === "breakdown" ? [`Visualization: ${report.chartStyle === "bar" ? "Horizontal bars" : "Donut chart"}`] : []),
  ] : [];
  const draftActiveFilterCount = draft ? [
    draft.status,
    draft.priority,
    draft.category.trim(),
    draft.assigneeId,
    draft.source,
    draft.ticketType,
    draft.resolutionState,
    draft.slaState,
  ].filter(Boolean).length : 0;
  const draftPeriodDays = draft
    ? Math.round((new Date(draft.endLocal).getTime() - new Date(draft.startLocal).getTime()) / (24 * 60 * 60 * 1000))
    : null;

  const applyDraft = () => {
    if (!draft) return;
    const nextReport = appliedReportFromDraft(draft);
    if (!nextReport) {
      setFilterError("Choose a valid start and end time. The start must be before the end.");
      return;
    }
    setFilterError("");
    setExportError("");
    setExportNotice("");
    setReport(nextReport);
  };

  const applyPreset = (days: number) => {
    const preset = presetDraft(days);
    const nextDraft = draft ? { ...draft, startLocal: preset.startLocal, endLocal: preset.endLocal } : preset;
    setDraft(nextDraft);
    setReport(appliedReportFromDraft(nextDraft));
    setFilterError("");
    setExportError("");
    setExportNotice("");
  };

  const resetReport = () => {
    const nextDraft = presetDraft(30);
    setDraft(nextDraft);
    setReport(appliedReportFromDraft(nextDraft));
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

  const updateDraft = <K extends keyof ReportDraft>(key: K, value: ReportDraft[K]) => {
    setDraft((current) => current ? { ...current, [key]: value } : current);
  };

  return (
    <PageFrame width="wide">
      <PageHeader eyebrow="Operational analytics" icon={<BarChart3 className="h-4 w-4" />} title="Reports" description="Generate the report you need, choose how to group it, refine the matching tickets, and export the evidence." />

      <section className="card-surface space-y-5 p-4 sm:p-5" aria-labelledby="report-builder-heading">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Filter className="h-4 w-4 text-semantic-primary" aria-hidden="true" />
              <h2 id="report-builder-heading" className="text-sm font-semibold text-ink-700">Report builder</h2>
            </div>
            <p className="mt-1 text-xs leading-5 text-ink-400">
              {report && filters
                ? `${REPORT_TYPES[report.type].label}${summary ? ` · ${summary.total_tickets.toLocaleString()} matching tickets` : ""}`
                : "Preparing the default 30-day reporting window…"}
            </p>
          </div>
          <Button variant="secondary" leadingIcon={<Download className="h-4 w-4" />} pending={exporting} pendingLabel="Exporting…" disabled={!filters || hasUnappliedChanges} onClick={() => void exportCsv()}>
            Export matching CSV
          </Button>
        </div>

        <div className="grid gap-5 rounded-xl border border-linen-300 bg-linen-100 p-4 lg:grid-cols-[minmax(16rem,0.8fr)_minmax(0,1.2fr)] lg:items-start">
          <label>
            <span className="mb-1.5 block text-xs font-semibold text-ink-500">Report type</span>
            <select className="input-base" value={draft?.reportType ?? "overview"} disabled={!draft} onChange={(event) => updateDraft("reportType", event.target.value as ReportType)}>
              {Object.entries(REPORT_TYPES).map(([value, item]) => <option key={value} value={value}>{item.label}</option>)}
            </select>
            <span className="mt-1.5 block text-xs leading-5 text-ink-400">{REPORT_TYPES[draft?.reportType ?? "overview"].description}</span>
          </label>
          <fieldset>
            <legend className="mb-1.5 text-xs font-semibold text-ink-500">Quick range</legend>
            <div className="flex flex-wrap gap-2" aria-label="Quick date ranges">
              {REPORT_PRESETS.map(([days, label]) => <Button key={days} size="sm" variant="ghost" aria-pressed={draftPeriodDays === days} onClick={() => applyPreset(days)}>{label}</Button>)}
            </div>
            <p className="mt-2 text-xs leading-5 text-ink-400">Choose a common period now, or set exact dates under Refine report.</p>
          </fieldset>
        </div>

        <div className="flex min-w-0 flex-wrap items-center gap-2" aria-label="Applied report criteria">
          <span className="text-[11px] font-semibold uppercase tracking-[0.1em] text-ink-400">Applied</span>
          {appliedCriteria.length > 0
            ? appliedCriteria.map((criterion) => <span key={criterion} className="max-w-full whitespace-normal break-words rounded-full border border-linen-400 bg-linen-100 px-3 py-1.5 text-[11px] font-semibold leading-4 text-ink-500 [overflow-wrap:anywhere]">{criterion}</span>)
            : <span className="text-xs text-ink-400">Preparing report criteria…</span>}
        </div>

        <details className="group rounded-xl border border-linen-300 bg-linen-50">
          <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 rounded-xl px-4 py-3 text-sm font-semibold text-ink-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] [&::-webkit-details-marker]:hidden">
            <span className="inline-flex items-center gap-2"><Filter className="h-4 w-4 text-semantic-primary" aria-hidden="true" />Refine report</span>
            <span className="text-xs font-normal text-ink-400">{draftActiveFilterCount ? `${draftActiveFilterCount} optional ${draftActiveFilterCount === 1 ? "filter" : "filters"}` : "Dates, grouping, and optional filters"}</span>
          </summary>
          <div className="space-y-5 border-t border-linen-300 p-4">
            {draft && draft.reportType !== "overview" && draft.reportType !== "volume" && (
              <div className="grid gap-4 sm:grid-cols-2">
                <label>
                  <span className="mb-1.5 block text-xs font-semibold text-ink-500">Group results by</span>
                  <select className="input-base" value={draft.groupBy} onChange={(event) => updateDraft("groupBy", event.target.value as ReportGroupBy)}>
                    {GROUP_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                </label>
                {draft.reportType === "breakdown" && <label>
                  <span className="mb-1.5 block text-xs font-semibold text-ink-500">Visualization</span>
                  <select className="input-base" value={draft.chartStyle} onChange={(event) => updateDraft("chartStyle", event.target.value as ChartStyle)}>
                    <option value="bar">Horizontal bars</option>
                    <option value="donut">Donut chart</option>
                  </select>
                </label>}
              </div>
            )}
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              <SelectField label="Time basis" value={draft?.dateField ?? "created"} disabled={!draft} onChange={(value) => updateDraft("dateField", value as ReportDateField)} options={[["created", "Ticket created time"], ["resolved", "Ticket resolved time"]]} />
              <label>
                <span className="mb-1.5 block text-xs font-semibold text-ink-500">From</span>
                <input type="datetime-local" className="input-base" value={draft?.startLocal ?? ""} disabled={!draft} onChange={(event) => updateDraft("startLocal", event.target.value)} />
              </label>
              <label>
                <span className="mb-1.5 block text-xs font-semibold text-ink-500">Through</span>
                <input type="datetime-local" className="input-base" value={draft?.endLocal ?? ""} disabled={!draft} onChange={(event) => updateDraft("endLocal", event.target.value)} />
              </label>
            </div>
            <div className="border-t border-linen-300 pt-5">
              <h3 className="text-xs font-semibold text-ink-600">Optional ticket filters</h3>
              <div className="mt-3 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                <SelectField label="Status" value={draft?.status ?? ""} disabled={!draft} onChange={(value) => updateDraft("status", value)} options={[["", "All statuses"], ...(optionsQuery.data?.statuses ?? []).map((value) => [value, value] as [string, string])]} />
                <SelectField label="Priority" value={draft?.priority ?? ""} disabled={!draft} onChange={(value) => updateDraft("priority", value)} options={[["", "All priorities"], ...(optionsQuery.data?.priorities ?? []).map((value) => [value, value] as [string, string])]} />
                <SelectField label="Category" value={draft?.category ?? ""} disabled={!draft} onChange={(value) => updateDraft("category", value)} options={[["", "All categories"], ...(optionsQuery.data?.categories ?? []).map((value) => [value, value] as [string, string])]} />
                <SelectField label="Assignee" value={draft?.assigneeId ?? ""} disabled={!draft} onChange={(value) => updateDraft("assigneeId", value)} options={[
                  ["", "All assignees"],
                  ...(optionsQuery.data?.has_unassigned ? [["__unassigned__", "Unassigned"] as [string, string]] : []),
                  ...(optionsQuery.data?.assignees ?? []).map((item) => [item.id, item.name] as [string, string]),
                ]} />
                <SelectField label="Source" value={draft?.source ?? ""} disabled={!draft} onChange={(value) => updateDraft("source", value)} options={[["", "All sources"], ...(optionsQuery.data?.sources ?? []).map((value) => [value, value] as [string, string])]} />
                <SelectField label="Ticket type" value={draft?.ticketType ?? ""} disabled={!draft} onChange={(value) => updateDraft("ticketType", value)} options={[["", "All ticket types"], ...(optionsQuery.data?.ticket_types ?? []).map((value) => [value, titleCase(value)] as [string, string])]} />
                <SelectField label="Resolution state" value={draft?.resolutionState ?? ""} disabled={!draft} onChange={(value) => updateDraft("resolutionState", value)} options={[["", "Open and resolved"], ["open", "Open only"], ["resolved", "Resolved only"]]} />
                <SelectField label="SLA state" value={draft?.slaState ?? ""} disabled={!draft} onChange={(value) => updateDraft("slaState", value)} options={[["", "All SLA states"], ["breached", "Breached"], ["within_sla", "Within SLA"], ["not_tracked", "Not tracked or paused"]]} />
              </div>
            </div>
            <div className="flex flex-col gap-3 border-t border-linen-300 pt-4 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-xs leading-5 text-ink-400">Times are entered in {timeZone} and sent to the report service as UTC.</p>
              <Button size="sm" variant="ghost" leadingIcon={<RotateCcw className="h-3.5 w-3.5" />} onClick={resetReport}>Reset all criteria</Button>
            </div>
          </div>
        </details>

        <div className="flex flex-col gap-3 border-t border-linen-300 pt-4 sm:flex-row sm:items-center sm:justify-between">
          <p className={cn("text-xs", hasUnappliedChanges ? "font-semibold text-semantic-warning" : "text-ink-400")}>
            {hasUnappliedChanges ? "The report definition has changed. Generate it to refresh the result and export." : "The generated result matches the applied criteria above."}
          </p>
          <Button size="sm" onClick={applyDraft} disabled={!draft || !hasUnappliedChanges}>Generate report</Button>
        </div>
      </section>

      {filterError && <Alert variant="danger" title="Check the report period">{filterError}</Alert>}
      {exportError && <Alert variant="danger" title="Export failed">{exportError}</Alert>}
      {exportNotice && <Alert variant="success" title="Export ready">{exportNotice}</Alert>}
      {optionsQuery.isError && <Alert variant="warning" title="Some filter choices are unavailable">Existing report criteria still work, but selectable values could not be loaded.</Alert>}

      {failed === activeQueries.length && (
        <ErrorState title="Report could not be loaded" description="The analytics service did not return data for this report." onRetry={() => void Promise.all(activeQueries.map((query) => query.refetch()))} retrying={activeQueries.some((query) => query.isFetching)} />
      )}
      {failed > 0 && failed < activeQueries.length && <Alert variant="warning" title="Partial report data">{failed} report {failed === 1 ? "section is" : "sections are"} unavailable. Available figures remain visible.</Alert>}

      {report && failed < activeQueries.length && <>
        <section className="card-surface flex flex-col gap-2 p-4 sm:flex-row sm:items-start sm:justify-between sm:p-5" aria-labelledby="generated-report-heading">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-semantic-primary">Generated report</p>
            <h2 id="generated-report-heading" className="mt-1 text-lg font-semibold text-ink-700">{REPORT_TYPES[report.type].label}</h2>
            <p className="mt-1 text-xs leading-5 text-ink-400">{REPORT_TYPES[report.type].description}{showSeries ? ` Grouped by ${groupLabel.toLowerCase()}.` : ""}</p>
          </div>
          <p className="text-xs text-ink-400">{reportPeriodLabel(report.filters)}</p>
        </section>

        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <KpiTile label="Matching tickets" value={summary?.total_tickets} icon={TicketIcon} loading={summaryQuery.isLoading} />
          <KpiTile label="Open" value={summary?.open_tickets} icon={Clock} color="text-semantic-info" loading={summaryQuery.isLoading} />
          <KpiTile label="Resolved" value={summary?.resolved_tickets} icon={CheckCircle2} color="text-semantic-success" loading={summaryQuery.isLoading} />
          <KpiTile label="SLA breached" value={summary?.breached_sla} icon={AlertTriangle} color="text-semantic-danger" loading={summaryQuery.isLoading} />
        </div>

        {report.type === "overview" && <>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <MiniStat label="Avg resolution time" value={summary ? `${summary.avg_resolution_hours}h` : "—"} loading={summaryQuery.isLoading} />
            <MiniStat label="Escalation rate" value={summary ? `${summary.escalation_rate}%` : "—"} loading={summaryQuery.isLoading} />
            <MiniStat label="CSAT" value={summary ? `${summary.csat_proxy}%` : "—"} loading={summaryQuery.isLoading} />
          </div>
          <VolumeChart data={volumeData} loading={volumeQuery.isLoading} error={volumeQuery.isError} onRetry={() => void volumeQuery.refetch()} />
          <div className="grid min-w-0 grid-cols-1 items-start gap-6 lg:grid-cols-2">
            <CategoryChart data={categoryData} response={categoryQuery.data} loading={categoryQuery.isLoading} error={categoryQuery.isError} onRetry={() => void categoryQuery.refetch()} />
            <BarSeriesCard title="Tickets by status" data={statusData} loading={statusQuery.isLoading} error={statusQuery.isError} onRetry={() => void statusQuery.refetch()} />
          </div>
        </>}

        {report.type === "volume" && <VolumeChart data={volumeData} loading={volumeQuery.isLoading} error={volumeQuery.isError} onRetry={() => void volumeQuery.refetch()} />}

        {showSeries && <CustomSeriesCard
          title={`${REPORT_TYPES[report.type].label} by ${groupLabel.toLowerCase()}`}
          data={seriesData}
          unit={seriesQuery.data?.unit}
          truncated={seriesQuery.data?.truncated ?? false}
          totalGroups={seriesQuery.data?.total_groups ?? 0}
          style={report.type === "breakdown" ? report.chartStyle : "bar"}
          loading={seriesQuery.isLoading}
          error={seriesQuery.isError}
          onRetry={() => void seriesQuery.refetch()}
        />}
      </>}
    </PageFrame>
  );
}

function SelectField({ label, value, disabled, options, onChange }: { label: string; value: string; disabled: boolean; options: Array<readonly [string, string]>; onChange: (value: string) => void }) {
  return (
    <label>
      <span className="mb-1.5 block text-xs font-semibold text-ink-500">{label}</span>
      <select className="input-base" value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)}>
        {options.map(([optionValue, optionLabel]) => <option key={`${optionValue}-${optionLabel}`} value={optionValue}>{optionLabel}</option>)}
      </select>
    </label>
  );
}

function VolumeChart({ data, loading, error, onRetry }: { data: Array<{ day: string; count: number }>; loading: boolean; error: boolean; onRetry: () => void }) {
  return (
    <div className="card-surface min-w-0 p-4 sm:p-5">
      <h2 className="mb-4 text-sm font-semibold text-ink-700">Ticket volume by day</h2>
      {loading ? <ChartSkeleton /> : error ? <SectionError onRetry={onRetry} /> : data.length > 0 ? (
        <><p className="sr-only">Daily ticket volume ranges from {Math.min(...data.map((item) => item.count))} to {Math.max(...data.map((item) => item.count))} tickets.</p><ResponsiveContainer width="100%" height={260}>
          <AreaChart data={data}>
            <defs><linearGradient id="volGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#803CE8" stopOpacity={0.3} /><stop offset="95%" stopColor="#803CE8" stopOpacity={0} /></linearGradient></defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#DDE2EA" vertical={false} />
            <XAxis dataKey="day" tick={{ fontSize: 10, fill: "#7E8691" }} interval="preserveStartEnd" />
            <YAxis tick={{ fontSize: 10, fill: "#7E8691" }} allowDecimals={false} />
            <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #DDE2EA" }} />
            <Area type="monotone" dataKey="count" stroke="#803CE8" strokeWidth={2} fill="url(#volGrad)" isAnimationActive={false} />
          </AreaChart>
        </ResponsiveContainer></>
      ) : <EmptyChart />}
    </div>
  );
}

function CategoryChart({ data, response, loading, error, onRetry }: { data: Array<{ name: string; value: number }>; response?: { total_categories: number; truncated: boolean }; loading: boolean; error: boolean; onRetry: () => void }) {
  return (
    <div className="card-surface min-w-0 p-4 sm:p-5">
      <h2 className="mb-4 text-sm font-semibold text-ink-700">Tickets by category</h2>
      {loading ? <ChartSkeleton /> : error ? <SectionError onRetry={onRetry} /> : data.length > 0 ? (
        <div className="space-y-4">
          {response?.truncated && <Alert variant="warning" title="Category view is limited" className="text-xs">Showing {data.length.toLocaleString()} of {response.total_categories.toLocaleString()} categories.</Alert>}
          <ResponsiveContainer width="100%" height={210}><PieChart><Pie data={data} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={78} innerRadius={40} isAnimationActive={false}>{data.map((_, index) => <Cell key={index} fill={CHART_COLORS[index % CHART_COLORS.length]} />)}</Pie><Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} /></PieChart></ResponsiveContainer>
          <ChartLegend label="Ticket category legend" data={data} />
        </div>
      ) : <EmptyChart />}
    </div>
  );
}

function BarSeriesCard({ title, data, loading, error, onRetry }: { title: string; data: Array<{ name: string; value: number }>; loading: boolean; error: boolean; onRetry: () => void }) {
  return (
    <div className="card-surface min-w-0 p-4 sm:p-5">
      <h2 className="mb-4 text-sm font-semibold text-ink-700">{title}</h2>
      {loading ? <ChartSkeleton /> : error ? <SectionError onRetry={onRetry} /> : data.length > 0 ? <HorizontalBarChart data={data} /> : <EmptyChart />}
    </div>
  );
}

function CustomSeriesCard({ title, data, unit, truncated, totalGroups, style, loading, error, onRetry }: { title: string; data: Array<{ name: string; value: number; count: number }>; unit?: "tickets" | "hours" | "percent"; truncated: boolean; totalGroups: number; style: ChartStyle; loading: boolean; error: boolean; onRetry: () => void }) {
  return (
    <div className="card-surface min-w-0 p-4 sm:p-5">
      <div className="mb-4">
        <h2 className="text-sm font-semibold text-ink-700">{title}</h2>
        <p className="mt-1 text-xs text-ink-400">{unit === "hours" ? "Average hours; the sample count includes resolved tickets only." : unit === "percent" ? "Compliance percentage; the sample count includes active tickets with tracked SLA deadlines." : "Matching ticket count."}</p>
      </div>
      {truncated && <Alert variant="warning" title="Grouped view is limited" className="mb-4 text-xs">Showing the first {data.length.toLocaleString()} of {totalGroups.toLocaleString()} groups.</Alert>}
      {loading ? <ChartSkeleton /> : error ? <SectionError onRetry={onRetry} /> : data.length > 0 ? style === "donut" ? (
        <div className="space-y-4">
          <ResponsiveContainer width="100%" height={280}><PieChart><Pie data={data} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={105} innerRadius={58} isAnimationActive={false}>{data.map((_, index) => <Cell key={index} fill={CHART_COLORS[index % CHART_COLORS.length]} />)}</Pie><Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} /></PieChart></ResponsiveContainer>
          <ChartLegend label="Custom report legend" data={data} suffix={unit === "percent" ? "%" : unit === "hours" ? "h" : ""} />
        </div>
      ) : <div className="space-y-4">
        <HorizontalBarChart data={data} suffix={unit === "percent" ? "%" : unit === "hours" ? "h" : ""} />
        {unit !== "tickets" && <ul className="grid gap-2 text-xs text-ink-500 sm:grid-cols-2" aria-label="Report sample sizes">
          {data.map((item) => <li key={item.name} className="flex min-w-0 justify-between gap-3 rounded-lg bg-linen-100 px-3 py-2"><span className="min-w-0 break-words [overflow-wrap:anywhere]">{item.name}</span><span className="shrink-0 font-semibold tabular-nums text-ink-700">{item.count.toLocaleString()} ticket{item.count === 1 ? "" : "s"}</span></li>)}
        </ul>}
      </div> : <EmptyChart />}
    </div>
  );
}

function HorizontalBarChart({ data, suffix = "" }: { data: Array<{ name: string; value: number }>; suffix?: string }) {
  return (
    <ResponsiveContainer width="100%" height={categoryChartHeight(data, "name")}>
      <BarChart data={data} layout="vertical" margin={{ left: 8, right: 24 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#DDE2EA" horizontal={false} />
        <XAxis type="number" tick={{ fontSize: 10, fill: "#7E8691" }} allowDecimals={suffix !== ""} unit={suffix} />
        <YAxis type="category" dataKey="name" tick={<WrappedYAxisTick />} width={140} interval={0} />
        <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #DDE2EA" }} formatter={(value) => `${String(value)}${suffix}`} />
        <Bar dataKey="value" radius={[0, 4, 4, 0]} isAnimationActive={false}>{data.map((_, index) => <Cell key={index} fill={CHART_COLORS[index % CHART_COLORS.length]} />)}</Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

function ChartLegend({ label, data, suffix = "" }: { label: string; data: Array<{ name: string; value: number }>; suffix?: string }) {
  return (
    <ul className="grid min-w-0 gap-2 sm:grid-cols-2" aria-label={label}>
      {data.map((item, index) => (
        <li key={`${item.name}-${index}`} className="flex min-w-0 items-start gap-2 rounded-lg bg-linen-100 px-3 py-2 text-xs">
          <span className="mt-1 h-2.5 w-2.5 shrink-0 rounded-sm" style={{ backgroundColor: CHART_COLORS[index % CHART_COLORS.length] }} aria-hidden="true" />
          <span className="min-w-0 flex-1 whitespace-normal break-words leading-5 text-ink-600 [overflow-wrap:anywhere]">{item.name}</span>
          <span className="shrink-0 font-semibold tabular-nums text-ink-700">{item.value.toLocaleString()}{suffix}</span>
        </li>
      ))}
    </ul>
  );
}

function KpiTile({ label, value, icon: Icon, color, loading }: { label: string; value?: number; icon: React.ElementType; color?: string; loading: boolean }) {
  return <div className="card-surface p-4"><div className="mb-2 flex items-center justify-between"><span className="text-[11px] font-semibold uppercase tracking-wider text-ink-400">{label}</span><Icon className={cn("h-4 w-4", color || "text-ink-400")} strokeWidth={1.5} /></div>{loading ? <Skeleton className="mt-3 h-8 w-20" /> : <p className="text-3xl font-semibold tracking-[-0.04em] text-ink-700 tabular-nums">{value == null ? "—" : value.toLocaleString()}</p>}</div>;
}

function MiniStat({ label, value, loading }: { label: string; value: string; loading: boolean }) {
  return <div className="card-surface flex min-w-0 flex-wrap items-center justify-between gap-2 p-4"><span className="min-w-0 whitespace-normal break-words text-sm text-ink-500 [overflow-wrap:anywhere]">{label}</span>{loading ? <Skeleton className="h-6 w-16" /> : <span className="shrink-0 text-lg font-bold text-ink-700 tabular-nums">{value}</span>}</div>;
}

function EmptyChart() {
  return <EmptyState className="min-h-[200px] border-0 bg-transparent" icon={<BarChart3 className="h-5 w-5" />} title="No data available" description="This report will populate when matching ticket activity exists." />;
}

function ChartSkeleton() { return <div className="space-y-4 py-3" aria-label="Loading report"><Skeleton className="h-44 w-full" /><Skeleton className="h-3 w-2/3" /></div>; }
function SectionError({ onRetry }: { onRetry: () => void }) { return <ErrorState className="min-h-[200px]" title="Report unavailable" description="This section could not be loaded." onRetry={onRetry} />; }
