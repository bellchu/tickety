"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  CheckCircle2,
  Mail,
  Search,
  Send,
  ShieldCheck,
  UserRound,
  Users,
  X,
} from "lucide-react";
import { Alert, Button, EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { PageFrame, PageHeader } from "@/components/layout/PageLayout";
import { api } from "@/lib/api";
import type { EmailAudience, EmailRecipient } from "@/lib/types";
import { cn } from "@/lib/utils";

const MAX_RECIPIENTS = 50;

function canUseEmail(context: Awaited<ReturnType<typeof api.getAuthMe>> | undefined) {
  if (!context || context.auth_kind !== "session" || !context.is_active) return false;
  const role = context.role.toLowerCase();
  if (!["admin", "supervisor", "agent"].includes(role)) return false;
  return context.app_mode === "production" || role === "admin";
}

export default function EmailPage() {
  const authQuery = useQuery({ queryKey: ["auth-me"], queryFn: api.getAuthMe, retry: false });
  const emailAccess = canUseEmail(authQuery.data);
  const [audience, setAudience] = useState<EmailAudience>("agents");
  const [search, setSearch] = useState("");
  const [directorySearch, setDirectorySearch] = useState("");
  const [selected, setSelected] = useState<EmailRecipient[]>([]);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");

  const statusQuery = useQuery({
    queryKey: ["email-status"],
    queryFn: api.getEmailStatus,
    enabled: emailAccess,
  });
  const recipientsQuery = useQuery({
    queryKey: ["email-recipients", audience, directorySearch],
    queryFn: () => api.getEmailRecipients(audience, directorySearch),
    enabled: emailAccess,
  });
  const sendMutation = useMutation({
    mutationFn: api.sendEmail,
    onSuccess: () => {
      setSelected([]);
      setSubject("");
      setBody("");
    },
  });

  const selectedIds = useMemo(() => new Set(selected.map((recipient) => recipient.id)), [selected]);
  const recipients = recipientsQuery.data?.recipients ?? [];
  const configured = statusQuery.data?.configured === true;
  const isAdmin = authQuery.data?.role.toLowerCase() === "admin";

  useEffect(() => {
    const timer = window.setTimeout(() => setDirectorySearch(search.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  const changeAudience = (nextAudience: EmailAudience) => {
    setAudience(nextAudience);
    setSelected([]);
    setSearch("");
    setDirectorySearch("");
    sendMutation.reset();
  };

  const toggleRecipient = (recipient: EmailRecipient) => {
    sendMutation.reset();
    setSelected((current) => {
      if (current.some((item) => item.id === recipient.id)) {
        return current.filter((item) => item.id !== recipient.id);
      }
      if (current.length >= MAX_RECIPIENTS) return current;
      return [...current, recipient];
    });
  };

  const selectVisible = () => {
    sendMutation.reset();
    setSelected((current) => {
      const next = [...current];
      const ids = new Set(next.map((recipient) => recipient.id));
      for (const recipient of recipients) {
        if (next.length >= MAX_RECIPIENTS) break;
        if (!ids.has(recipient.id)) {
          ids.add(recipient.id);
          next.push(recipient);
        }
      }
      return next;
    });
  };

  if (authQuery.isLoading) {
    return <PageFrame className="max-w-6xl"><Skeleton className="h-28 w-full" /><Skeleton className="h-96 w-full" /></PageFrame>;
  }

  if (authQuery.isError) {
    return <ErrorState title="Email access could not be checked" description="Your session could not be verified, so no recipient data was requested." actionLabel="Retry access check" onRetry={() => void authQuery.refetch()} retrying={authQuery.isFetching} />;
  }

  if (!emailAccess) {
    return (
      <EmptyState
        className="mx-auto min-h-80 max-w-2xl"
        icon={<ShieldCheck className="h-5 w-5" />}
        title={authQuery.data?.auth_kind === "demo_fallback" ? "Sign in to send email" : "Email access is unavailable"}
        description={authQuery.data?.app_mode === "demo" ? "Demo email delivery is limited to an authenticated administrator so public or non-admin demo sessions cannot create billable sends." : "An active agent, supervisor, or administrator session is required."}
        action={authQuery.data?.auth_kind === "demo_fallback" ? <Link href="/login?next=/email" className="inline-flex min-h-10 items-center justify-center rounded-lg bg-semantic-primary px-4 text-sm font-semibold text-white">Sign in</Link> : undefined}
      />
    );
  }

  return (
    <PageFrame className="max-w-6xl">
      <PageHeader eyebrow="Team communication" icon={<Mail className="h-5 w-5" />} title="Email" description="Send private SendGrid deliveries to team agents or synced end users." />

      {statusQuery.isLoading ? (
        <Skeleton className="h-20 w-full" />
      ) : statusQuery.isError ? (
        <Alert variant="danger" title="Email status unavailable" action={<Button size="sm" variant="secondary" onClick={() => void statusQuery.refetch()}>Retry</Button>}>
          Tickety could not confirm whether SendGrid is configured.
        </Alert>
      ) : configured ? (
        <Alert variant="success" title="SendGrid is ready">
          Messages are sent from the verified {statusQuery.data?.from_name || "Tickety"} sender. Recipient addresses remain private from one another.
        </Alert>
      ) : (
        <Alert variant="warning" title="SendGrid setup required" action={isAdmin ? <Link href="/settings#settings-email" className="text-xs font-semibold text-semantic-primary hover:underline">Configure email</Link> : undefined}>
          An administrator must save a SendGrid API key and verified sender email before messages can be sent.
        </Alert>
      )}

      {sendMutation.isSuccess && (
        <Alert variant="success" title="Email accepted by SendGrid">
          <span className="inline-flex items-center gap-2"><CheckCircle2 className="h-4 w-4" />{sendMutation.data.recipient_count} private deliver{sendMutation.data.recipient_count === 1 ? "y" : "ies"} accepted.</span>
        </Alert>
      )}
      {sendMutation.isError && (
        <Alert variant="danger" title="Email was not sent">
          {sendMutation.error instanceof Error ? sendMutation.error.message : "SendGrid did not accept the message."}
        </Alert>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <section className="overflow-hidden rounded-2xl border border-linen-400 bg-linen-50 shadow-sm" aria-labelledby="email-recipient-heading">
          <div className="border-b border-linen-400 p-4 sm:p-5">
            <h2 id="email-recipient-heading" className="text-sm font-semibold text-ink-700">Choose recipients</h2>
            <p className="mt-1 text-xs leading-5 text-ink-500">Select up to {MAX_RECIPIENTS} recipients from one audience per message.</p>
            <div className="mt-4 grid grid-cols-2 gap-2" role="group" aria-label="Recipient audience">
              <AudienceButton active={audience === "agents"} icon={Users} label="Agents" description="Tickety and synced agents" onClick={() => changeAudience("agents")} />
              <AudienceButton active={audience === "users"} icon={UserRound} label="Users" description="Synced requesters" onClick={() => changeAudience("users")} />
            </div>
            <label className="relative mt-4 block">
              <span className="sr-only">Search {audience}</span>
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" aria-hidden="true" />
              <input className="input-base input-search w-full" type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder={`Search ${audience} by name, email, or title`} />
            </label>
          </div>

          <div className="flex items-center justify-between border-b border-linen-300 bg-linen-100 px-4 py-2.5 text-xs text-ink-500">
            <span>{recipientsQuery.data ? `${recipientsQuery.data.total}${recipientsQuery.data.truncated ? "+" : ""} matching · ${selected.length} selected` : "Loading directory…"}</span>
            <button type="button" onClick={selectVisible} disabled={!recipients.length || selected.length >= MAX_RECIPIENTS} className="font-semibold text-semantic-primary hover:underline disabled:opacity-50">Select visible</button>
          </div>

          <div className="max-h-[30rem] overflow-y-auto">
            {recipientsQuery.data?.truncated && <p className="border-b border-linen-300 bg-amber-50 px-4 py-2 text-xs text-amber-800">Showing the first matches. Refine your search to find someone else.</p>}
            {recipientsQuery.isLoading ? (
              <div className="space-y-2 p-4">{[1, 2, 3, 4].map((item) => <Skeleton key={item} className="h-14 w-full" />)}</div>
            ) : recipientsQuery.isError ? (
              <ErrorState className="m-4" title="Recipient directory unavailable" description="No addresses were loaded." onRetry={() => void recipientsQuery.refetch()} retrying={recipientsQuery.isFetching} />
            ) : recipients.length === 0 ? (
              <EmptyState className="m-4 min-h-48" icon={audience === "agents" ? <Users className="h-5 w-5" /> : <UserRound className="h-5 w-5" />} title={`No ${audience} found`} description={search ? "Try a different search." : audience === "users" ? "Refresh the external ITSM directory in Settings to load requesters." : "No active agents with deliverable email addresses are available."} />
            ) : (
              <div className="divide-y divide-linen-300">
                {recipients.map((recipient) => {
                  const checked = selectedIds.has(recipient.id);
                  return (
                    <label key={recipient.id} className={cn("flex cursor-pointer items-start gap-3 px-4 py-3 transition-colors hover:bg-linen-100", checked && "bg-clay-50")}>
                      <input type="checkbox" className="mt-1 h-4 w-4 rounded border-linen-500 text-semantic-primary" checked={checked} disabled={!checked && selected.length >= MAX_RECIPIENTS} onChange={() => toggleRecipient(recipient)} />
                      <span className="min-w-0 flex-1">
                        <span className="block whitespace-normal break-words text-sm font-semibold text-ink-700 [overflow-wrap:anywhere]">{recipient.name}</span>
                        <span className="mt-0.5 block whitespace-normal break-words text-xs text-ink-500 [overflow-wrap:anywhere]">{recipient.email}</span>
                        <span className="mt-1 block text-[11px] capitalize text-ink-400">{recipient.title || "No title"} · {recipient.source}</span>
                      </span>
                    </label>
                  );
                })}
              </div>
            )}
          </div>
        </section>

        <form
          className="rounded-2xl border border-linen-400 bg-linen-50 p-4 shadow-sm sm:p-5"
          onSubmit={(event) => {
            event.preventDefault();
            sendMutation.mutate({
              audience,
              recipient_ids: selected.map((recipient) => recipient.id),
              subject: subject.trim(),
              body: body.trim(),
            });
          }}
        >
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-sm font-semibold text-ink-700">Compose message</h2>
              <p className="mt-1 text-xs leading-5 text-ink-500">Plain-text delivery with your Tickety identity added to the footer.</p>
            </div>
            <span className="rounded-full border border-linen-400 bg-linen-100 px-2.5 py-1 text-[11px] font-semibold capitalize text-ink-500">{audience}</span>
          </div>

          <div className="mt-5 space-y-4">
            <div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm font-medium text-ink-700">To</span>
                {selected.length > 0 && <button type="button" className="text-xs font-semibold text-ink-400 hover:text-ink-600" onClick={() => setSelected([])}>Clear all</button>}
              </div>
              <div className="mt-2 min-h-14 rounded-lg border border-linen-400 bg-linen-100 p-2">
                {selected.length === 0 ? <span className="px-1 text-xs text-ink-400">Choose recipients from the directory.</span> : (
                  <div className="flex flex-wrap gap-1.5">
                    {selected.slice(0, 6).map((recipient) => (
                      <button key={recipient.id} type="button" onClick={() => toggleRecipient(recipient)} className="inline-flex max-w-full items-center gap-1 rounded-full border border-clay-400/30 bg-clay-50 px-2 py-1 text-xs font-medium text-clay-700" title={`Remove ${recipient.name}`}>
                        <span className="min-w-0 whitespace-normal break-words [overflow-wrap:anywhere]">{recipient.name}</span><X className="h-3 w-3 shrink-0" aria-hidden="true" />
                      </button>
                    ))}
                    {selected.length > 6 && <details className="w-full rounded-lg border border-linen-300 bg-white px-2 py-1.5">
                      <summary className="cursor-pointer text-xs font-semibold text-ink-500">{selected.length - 6} more recipient{selected.length - 6 === 1 ? "" : "s"}</summary>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {selected.slice(6).map((recipient) => (
                          <button key={recipient.id} type="button" onClick={() => toggleRecipient(recipient)} className="inline-flex max-w-full items-center gap-1 rounded-full border border-clay-400/30 bg-clay-50 px-2 py-1 text-xs font-medium text-clay-700" title={`Remove ${recipient.name}`}>
                            <span className="min-w-0 whitespace-normal break-words [overflow-wrap:anywhere]">{recipient.name}</span><X className="h-3 w-3 shrink-0" aria-hidden="true" />
                          </button>
                        ))}
                      </div>
                    </details>}
                  </div>
                )}
              </div>
            </div>

            <label className="block">
              <span className="text-sm font-medium text-ink-700">Subject</span>
              <input className="input-base mt-2 w-full" required maxLength={200} value={subject} onChange={(event) => { setSubject(event.target.value); sendMutation.reset(); }} placeholder="How can we help?" />
              <span className="mt-1 block text-right text-[11px] text-ink-400">{subject.length}/200</span>
            </label>

            <label className="block">
              <span className="text-sm font-medium text-ink-700">Message</span>
              <textarea className="input-base mt-2 min-h-64 w-full resize-y py-3" required maxLength={50000} value={body} onChange={(event) => { setBody(event.target.value); sendMutation.reset(); }} placeholder="Write a clear message…" />
              <span className="mt-1 block text-right text-[11px] text-ink-400">{body.length.toLocaleString()}/50,000</span>
            </label>
          </div>

          <div className="mt-5 flex flex-col gap-3 border-t border-linen-300 pt-4 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs leading-5 text-ink-400">Each recipient gets an independent delivery; addresses are never shared in To or CC fields.</p>
            <Button type="submit" disabled={!configured || selected.length === 0 || !subject.trim() || !body.trim()} pending={sendMutation.isPending} pendingLabel="Sending…" leadingIcon={<Send className="h-4 w-4" />}>
              Send email
            </Button>
          </div>
        </form>
      </div>
    </PageFrame>
  );
}

function AudienceButton({ active, icon: Icon, label, description, onClick }: { active: boolean; icon: typeof Users; label: string; description: string; onClick: () => void }) {
  return (
    <button type="button" aria-pressed={active} onClick={onClick} className={cn("flex min-h-16 items-center gap-3 rounded-xl border px-3 text-left transition-colors", active ? "border-clay-400 bg-clay-50 text-clay-700" : "border-linen-400 bg-linen-50 text-ink-600 hover:bg-linen-100")}>
      <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
      <span className="min-w-0"><span className="block text-sm font-semibold">{label}</span><span className="block text-[11px] text-ink-400">{description}</span></span>
    </button>
  );
}
