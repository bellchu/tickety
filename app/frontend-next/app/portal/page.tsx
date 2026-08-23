"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  CalendarClock,
  Check,
  Clipboard,
  ExternalLink,
  FileCheck2,
  KeyRound,
  LifeBuoy,
  LockKeyhole,
  Send,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { TicketyLogo } from "@/components/layout/TicketyLogo";
import { LoginLink } from "@/components/layout/LoginLink";
import { Alert, Badge, Button, Dialog, ErrorState, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type { PortalTicket, PortalTicketCreated } from "@/lib/types";

const PRIORITIES = [
  { value: "P4", label: "Low", description: "General question or minor inconvenience" },
  { value: "P3", label: "Medium", description: "Work is affected, but a workaround exists" },
  { value: "P2", label: "High", description: "Important work is blocked" },
  { value: "P1", label: "Urgent", description: "Critical service or business impact" },
];

const statusVariant = (status: string): "neutral" | "info" | "success" | "warning" => {
  const normalized = status.toLowerCase().replace(/[_-]/g, " ");
  if (["resolved", "closed", "completed"].includes(normalized)) return "success";
  if (["in progress", "pending", "waiting"].includes(normalized)) return "warning";
  if (["new", "open"].includes(normalized)) return "info";
  return "neutral";
};

function extractAccessToken(value: string): string {
  const input = value.trim();
  if (!input) return "";

  try {
    const parsed = new URL(input, window.location.origin);
    const fragment = new URLSearchParams(parsed.hash.replace(/^#/, ""));
    const token = fragment.get("token");
    if (token) return token.trim();
    if (input.includes("#") || input.includes("?") || input.includes("/")) return "";
  } catch {
    return "";
  }

  return input;
}

function formatDate(value: string | null, options?: Intl.DateTimeFormatOptions) {
  if (!value) return "Not available";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Not available";
  return new Intl.DateTimeFormat(undefined, options ?? {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function TicketResult({ ticket }: { ticket: PortalTicket }) {
  return (
    <section aria-labelledby="request-result-title" className="overflow-hidden rounded-2xl border border-linen-400 bg-linen-50 shadow-[var(--shadow-raised)]">
      <div className="border-b border-linen-300 bg-linen-100 px-5 py-4 sm:px-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.12em] text-ink-400">Request found</p>
            <h2 id="request-result-title" className="mt-1 font-mono text-sm font-semibold text-ink-700">
              {ticket.id}
            </h2>
          </div>
          <Badge variant={statusVariant(ticket.status)} dot className="capitalize">
            {ticket.status.replace(/[_-]/g, " ")}
          </Badge>
        </div>
      </div>
      <div className="px-5 py-5 sm:px-6 sm:py-6">
        <h3 className="text-lg font-semibold tracking-[-0.015em] text-ink-700">{ticket.subject}</h3>
        <dl className="mt-6 grid gap-4 border-t border-linen-300 pt-5 sm:grid-cols-3">
          <div>
            <dt className="text-xs font-medium text-ink-400">Priority</dt>
            <dd className="mt-1 text-sm font-semibold text-ink-700">{ticket.priority}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-ink-400">Submitted</dt>
            <dd className="mt-1 text-sm font-medium text-ink-600">
              {formatDate(ticket.created_at, { dateStyle: "medium" })}
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-ink-400">Last updated</dt>
            <dd className="mt-1 text-sm font-medium text-ink-600">
              {formatDate(ticket.updated_at, { dateStyle: "medium" })}
            </dd>
          </div>
        </dl>
      </div>
    </section>
  );
}

export default function PortalPage() {
  const [reporter, setReporter] = useState("");
  const [subject, setSubject] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState("P3");
  const [tokenInput, setTokenInput] = useState("");
  const [lookupToken, setLookupToken] = useState("");
  const [lookupInputError, setLookupInputError] = useState("");
  const [createdTicket, setCreatedTicket] = useState<PortalTicketCreated | null>(null);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "error">("idle");
  const runtime = useQuery({
    queryKey: ["runtimeHealth"],
    queryFn: api.getHealth,
    staleTime: 60_000,
    retry: false,
  });
  const isDemoPortal = runtime.data?.mode === "demo";

  const lookup = useQuery({
    queryKey: ["portalTicket", lookupToken],
    queryFn: () => api.portalGetTicket(lookupToken),
    enabled: Boolean(lookupToken),
    retry: false,
  });

  useEffect(() => {
    const fragment = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const linkedToken = fragment.get("token");
    if (!linkedToken) return;

    const token = linkedToken.trim();
    if (token) {
      setTokenInput(token);
      setLookupToken(token);
    }

    // Remove capability material from the address bar and history immediately
    // after the client receives it. It remains only in this page's memory.
    window.history.replaceState(window.history.state, "", window.location.pathname + window.location.search);
  }, []);

  const createTicket = useMutation({
    mutationFn: () => api.portalCreateTicket(subject.trim(), description.trim(), reporter.trim(), priority),
    onSuccess: (created) => {
      setCreatedTicket(created);
      setCopyState("idle");
      setReporter("");
      setSubject("");
      setDescription("");
      setPriority("P3");
    },
  });

  const handleCreate = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!createTicket.isPending) createTicket.mutate();
  };

  const handleLookup = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const token = extractAccessToken(tokenInput);
    if (!token) {
      setLookupInputError("Paste the complete tracking link or access token supplied when the request was created.");
      return;
    }

    setLookupInputError("");
    if (token === lookupToken) {
      void lookup.refetch();
    } else {
      setLookupToken(token);
    }
  };

  const copyTrackingLink = async () => {
    if (!createdTicket) return;
    try {
      await navigator.clipboard.writeText(createdTicket.tracking_url);
      setCopyState("copied");
    } catch {
      setCopyState("error");
    }
  };

  const closeCreatedTicket = () => {
    setCreatedTicket(null);
    setCopyState("idle");
    createTicket.reset();
  };

  return (
    <div className="min-h-screen bg-linen-100 text-ink-700">
      <a href="#portal-main" className="fixed left-4 top-3 z-[120] -translate-y-20 rounded-lg bg-semantic-primary px-3 py-2 text-sm font-semibold text-white shadow-lg transition-transform focus:translate-y-0">
        Skip to content
      </a>

      <header className="border-b border-linen-300 bg-linen-50/95 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6 lg:px-8">
          <TicketyLogo />
          <div className="flex items-center gap-3">
            <div className="hidden items-center gap-2 text-xs font-medium text-ink-500 sm:flex">
              <ShieldCheck className="h-4 w-4 text-semantic-success" aria-hidden="true" />
              {isDemoPortal ? "Secure requester portal" : "Read-only Freshservice sidecar"}
            </div>
            <LoginLink
              label="Agent sign in"
              nextPath="/"
              className="border-linen-400 bg-white text-ink-700 shadow-sm hover:bg-linen-200"
            />
          </div>
        </div>
      </header>

      <main id="portal-main" tabIndex={-1} className="outline-none">
        <section className="relative overflow-hidden border-b border-linen-300 bg-linen-50">
          <div className="pointer-events-none absolute right-[-8rem] top-[-12rem] h-[28rem] w-[28rem] rounded-full bg-[var(--color-primary-soft)] blur-3xl" aria-hidden="true" />
          <div className="relative mx-auto grid max-w-6xl gap-8 px-4 py-12 sm:px-6 sm:py-16 lg:grid-cols-[1.15fr_0.85fr] lg:items-center lg:gap-16 lg:px-8 lg:py-20">
            <div>
              <Badge variant="info" icon={<Sparkles className="h-3 w-3" />}>Support that keeps you moving</Badge>
              <h1 className="mt-5 max-w-2xl font-serif text-4xl leading-[1.05] tracking-[-0.035em] text-ink-700 sm:text-5xl lg:text-[3.5rem]">
                {isDemoPortal
                  ? "Tell us what is getting in your way."
                  : "Keep Freshservice as your system of record."}
              </h1>
              <p className="mt-5 max-w-xl text-base leading-7 text-ink-500 sm:text-lg">
                {isDemoPortal
                  ? "Submit a support request in a few minutes. You will receive a private tracking link to follow its progress—no account required."
                  : "Create and update requests in your organization’s Freshservice portal. Tickety only imports provider data for local analysis and never writes ticket changes back."}
              </p>
              <div className="mt-7 flex flex-wrap gap-x-6 gap-y-3 text-sm text-ink-500">
                <span className="inline-flex items-center gap-2"><Check className="h-4 w-4 text-semantic-success" aria-hidden="true" />Clear request updates</span>
                <span className="inline-flex items-center gap-2"><Check className="h-4 w-4 text-semantic-success" aria-hidden="true" />Private, token-based access</span>
              </div>
            </div>

            <form onSubmit={handleLookup} className="rounded-2xl border border-linen-400 bg-linen-50 p-5 shadow-[var(--shadow-raised)] sm:p-6" aria-labelledby="track-request-title">
              <div className="flex items-start gap-3">
                <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-[var(--color-primary-soft)] text-semantic-primary" aria-hidden="true">
                  <KeyRound className="h-5 w-5" />
                </div>
                <div>
                  <h2 id="track-request-title" className="text-base font-semibold text-ink-700">Track an existing request</h2>
                  <p className="mt-1 text-sm leading-5 text-ink-500">Use the private link or token you received after submitting.</p>
                </div>
              </div>
              <label htmlFor="tracking-token" className="mt-5 block text-xs font-semibold text-ink-600">Tracking link or access token</label>
              <div className="relative mt-1.5">
                <LockKeyhole className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" aria-hidden="true" />
                <input
                  id="tracking-token"
                  type="password"
                  value={tokenInput}
                  onChange={(event) => {
                    setTokenInput(event.target.value);
                    if (lookupInputError) setLookupInputError("");
                  }}
                  className="input-base !pl-10 font-mono text-xs"
                  placeholder="Paste your private tracking link"
                  autoComplete="off"
                  autoCapitalize="none"
                  spellCheck={false}
                  aria-invalid={Boolean(lookupInputError)}
                  aria-describedby={lookupInputError ? "tracking-token-error" : "tracking-token-help"}
                />
              </div>
              <p id="tracking-token-help" className="mt-2 text-xs leading-5 text-ink-400">Treat this link like a password. It grants access to your request.</p>
              {lookupInputError && <p id="tracking-token-error" role="alert" className="mt-2 text-xs leading-5 text-semantic-danger">{lookupInputError}</p>}
              <Button type="submit" className="mt-4 w-full" pending={lookup.isFetching} pendingLabel="Checking securely…" trailingIcon={<ArrowRight className="h-4 w-4" />}>
                View request
              </Button>
            </form>
          </div>
        </section>

        <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6 sm:py-14 lg:px-8">
          {lookupToken && (
            <div className="mb-10" aria-live="polite">
              {lookup.isLoading ? (
                <section aria-label="Loading request" aria-busy="true" className="rounded-2xl border border-linen-400 bg-linen-50 p-6">
                  <span className="sr-only">Loading request</span>
                  <Skeleton className="h-4 w-28" />
                  <Skeleton className="mt-5 h-7 w-2/3" />
                  <div className="mt-7 grid gap-4 sm:grid-cols-3"><Skeleton className="h-12" /><Skeleton className="h-12" /><Skeleton className="h-12" /></div>
                </section>
              ) : lookup.isError ? (
                <ErrorState
                  title="This tracking link is invalid or has expired"
                  description="For your privacy, we cannot confirm whether a request exists. Check that you pasted the complete link, or contact your support team for help."
                  actionLabel="Try this link again"
                  onRetry={() => void lookup.refetch()}
                  retrying={lookup.isFetching}
                />
              ) : lookup.data ? <TicketResult ticket={lookup.data} /> : null}
            </div>
          )}

          {isDemoPortal ? (
          <div className="grid gap-8 lg:grid-cols-[0.72fr_1.28fr] lg:gap-12">
            <aside className="lg:pt-4">
              <div className="grid h-11 w-11 place-items-center rounded-xl bg-ink-700 text-linen-50" aria-hidden="true"><LifeBuoy className="h-5 w-5" /></div>
              <h2 className="mt-5 font-serif text-3xl tracking-[-0.025em] text-ink-700">Create a new request</h2>
              <p className="mt-3 text-sm leading-6 text-ink-500">Share enough detail for the support team to understand the impact and start resolving the issue.</p>
              <div className="mt-6 space-y-4 border-t border-linen-300 pt-6 text-sm text-ink-500">
                <div className="flex gap-3"><FileCheck2 className="mt-0.5 h-4 w-4 shrink-0 text-semantic-primary" aria-hidden="true" /><span>Describe what happened and what you expected.</span></div>
                <div className="flex gap-3"><CalendarClock className="mt-0.5 h-4 w-4 shrink-0 text-semantic-primary" aria-hidden="true" /><span>Choose urgency based on the current business impact.</span></div>
                <div className="flex gap-3"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-semantic-primary" aria-hidden="true" /><span>Save the tracking link shown after submission.</span></div>
              </div>
            </aside>

            <form onSubmit={handleCreate} className="rounded-2xl border border-linen-400 bg-linen-50 p-5 shadow-sm sm:p-7" aria-labelledby="new-request-form-title">
              <h2 id="new-request-form-title" className="sr-only">New support request details</h2>
              <div className="grid gap-5 sm:grid-cols-2">
                <label className="block sm:col-span-2">
                  <span className="text-xs font-semibold text-ink-600">Work email</span>
                  <input type="email" required value={reporter} onChange={(event) => setReporter(event.target.value)} className="input-base mt-1.5" placeholder="you@company.com" autoComplete="email" />
                  <span className="mt-1.5 block text-xs text-ink-400">Used by the support team to contact you about this request.</span>
                </label>
                <label className="block sm:col-span-2">
                  <span className="text-xs font-semibold text-ink-600">What do you need help with?</span>
                  <input required maxLength={200} value={subject} onChange={(event) => setSubject(event.target.value)} className="input-base mt-1.5" placeholder="A short summary of the issue" />
                </label>
                <label className="block sm:col-span-2">
                  <span className="text-xs font-semibold text-ink-600">Details</span>
                  <textarea required value={description} onChange={(event) => setDescription(event.target.value)} className="input-base mt-1.5 min-h-36 resize-y" placeholder="What happened? When did it start? Include any error messages or steps you have already tried." rows={6} />
                </label>
                <label className="block sm:col-span-2">
                  <span className="text-xs font-semibold text-ink-600">Impact</span>
                  <select value={priority} onChange={(event) => setPriority(event.target.value)} className="input-base mt-1.5">
                    {PRIORITIES.map((item) => <option key={item.value} value={item.value}>{item.label} — {item.description}</option>)}
                  </select>
                </label>
              </div>

              {createTicket.isError && (
                <Alert variant="danger" title="We could not submit your request" className="mt-5">
                  Nothing was saved. Check your connection and try again.
                </Alert>
              )}

              <div className="mt-6 flex flex-col-reverse items-stretch gap-3 border-t border-linen-300 pt-5 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-xs leading-5 text-ink-400"><LockKeyhole className="mr-1 inline h-3.5 w-3.5" aria-hidden="true" />Your tracking link is shown only once.</p>
                <Button type="submit" pending={createTicket.isPending} pendingLabel="Submitting securely…" leadingIcon={<Send className="h-4 w-4" />}>
                  Submit request
                </Button>
              </div>
            </form>
          </div>
          ) : (
            <section className="rounded-2xl border border-linen-400 bg-linen-50 p-6 shadow-sm sm:p-8" aria-labelledby="freshservice-authority-title">
              <Badge variant="info" icon={<ShieldCheck className="h-3 w-3" />}>Freshservice is authoritative</Badge>
              <h2 id="freshservice-authority-title" className="mt-4 font-serif text-3xl tracking-[-0.025em] text-ink-700">Submit requests in Freshservice</h2>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-ink-500">
                This production Tickety deployment is intentionally read-only. Use your organization’s Freshservice portal to create, edit, reply to, or close a ticket.
              </p>
            </section>
          )}
        </div>
      </main>

      <footer className="border-t border-linen-300 bg-linen-50">
        <div className="mx-auto flex max-w-6xl flex-col gap-2 px-4 py-6 text-xs text-ink-400 sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-8">
          <span>Powered by Tickety Service Operations</span>
          <span>Private by design · No account required</span>
        </div>
      </footer>

      <Dialog
        open={Boolean(createdTicket)}
        onOpenChange={(open) => { if (!open) closeCreatedTicket(); }}
        title="Your request is on its way"
        description="Save this private tracking link now. For your security, it cannot be recovered or shown again after you close this window."
        closeLabel="Close and discard tracking link"
        className="max-w-xl"
        footer={
          <>
            <Button variant="secondary" onClick={closeCreatedTicket}>I have saved it</Button>
            <Button onClick={() => createdTicket && window.open(createdTicket.tracking_url, "_blank", "noopener,noreferrer")} leadingIcon={<ExternalLink className="h-4 w-4" />}>
              Open request
            </Button>
          </>
        }
      >
        {createdTicket && (
          <div>
            <Alert variant="warning" title="This is the only copy">
              Anyone with this link can view the request. Keep it private and store it somewhere safe before continuing.
            </Alert>
            <div className="mt-5 rounded-xl border border-linen-400 bg-linen-100 p-4">
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs font-semibold uppercase tracking-[0.1em] text-ink-400">Private tracking link</span>
                <Badge variant="success" dot>Request created</Badge>
              </div>
              <p className="mt-3 break-all font-mono text-xs leading-5 text-ink-600">{createdTicket.tracking_url}</p>
              <Button variant="secondary" size="sm" className="mt-4 w-full sm:w-auto" onClick={copyTrackingLink} leadingIcon={copyState === "copied" ? <Check className="h-4 w-4" /> : <Clipboard className="h-4 w-4" />}>
                {copyState === "copied" ? "Link copied" : "Copy tracking link"}
              </Button>
              <div aria-live="polite" className="mt-2 min-h-5 text-xs">
                {copyState === "copied" && <span className="text-semantic-success">Copied. Save it in a secure place.</span>}
                {copyState === "error" && <span role="alert" className="text-semantic-danger">Copy failed. Select and copy the link above manually.</span>}
              </div>
            </div>
            <dl className="mt-5 grid gap-4 sm:grid-cols-2">
              <div><dt className="text-xs text-ink-400">Request ID</dt><dd className="mt-1 break-all font-mono text-xs font-semibold text-ink-700">{createdTicket.id}</dd></div>
              <div><dt className="text-xs text-ink-400">Link expires</dt><dd className="mt-1 text-sm font-semibold text-ink-700">{formatDate(createdTicket.access_expires_at)}</dd></div>
            </dl>
          </div>
        )}
      </Dialog>
    </div>
  );
}
