"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { Download, Image as ImageIcon, LockKeyhole, MessageSquareText, Paperclip } from "lucide-react";
import { api } from "@/lib/api";
import type { Ticket, TicketAttachment, TicketComment } from "@/lib/types";
import { formatTimeAgo } from "@/lib/utils";
import { formatOperationalTimestamp, requesterEmail, requesterName, safeMailto } from "@/lib/ticket-display";
import { Alert, Button, Skeleton } from "@/components/ui";

const COMMENT_PAGE_SIZE = 500;

type ThreadTicket = Pick<
  Ticket,
  | "id"
  | "description"
  | "reporter"
  | "requester_name"
  | "requester_email"
  | "requester_title"
  | "created_at"
  | "external_created_at"
>;

export function formatThreadTimestamp(value: string | null): string {
  return formatOperationalTimestamp(value);
}

export function mergeChronologicalCommentPages(
  pages: TicketComment[][],
): TicketComment[] {
  return [...pages].reverse().flat();
}

function ThreadPost({
  position,
  author,
  authorEmail,
  authorTitle,
  authorType,
  body,
  createdAt,
  isOriginal = false,
  isPrivate = false,
  attachments = [],
}: {
  position: number;
  author: string;
  authorEmail?: string | null;
  authorTitle?: string | null;
  authorType?: "agent" | "requester" | null;
  body: string;
  createdAt: string | null;
  isOriginal?: boolean;
  isPrivate?: boolean;
  attachments?: TicketAttachment[];
}) {
  const timestamp = formatThreadTimestamp(createdAt);
  const emailHref = safeMailto(authorEmail);

  return (
    <article
      className="overflow-hidden rounded-xl border border-linen-300 bg-white sm:grid sm:grid-cols-[10rem_minmax(0,1fr)]"
      data-thread-post={isOriginal ? "original" : "reply"}
    >
      <header className="border-b border-linen-300 bg-linen-100 px-4 py-3 sm:border-b-0 sm:border-r">
        <div className="flex items-center justify-between gap-2 sm:block">
          <span className="font-mono text-xs font-semibold text-semantic-primary">#{position}</span>
          {isOriginal && (
            <span className="badge border-clay-200 bg-[var(--color-primary-soft)] text-semantic-primary sm:mt-2">
              Original post
            </span>
          )}
        </div>
        <p className="mt-2 break-words text-xs font-semibold text-ink-700">{author || "Unknown author"}</p>
        {authorType && <p className="mt-0.5 text-[10px] font-medium uppercase tracking-wide text-ink-400">{authorType}</p>}
        {authorTitle && <p className="mt-1 break-words text-[10px] leading-4 text-ink-500">{authorTitle}</p>}
        {authorEmail && (
          emailHref
            ? <a href={emailHref} className="mt-1 block break-all text-[10px] leading-4 text-semantic-primary hover:underline">{authorEmail}</a>
            : <p className="mt-1 break-all text-[10px] leading-4 text-ink-400">{authorEmail}</p>
        )}
        <time
          className="mt-1 block font-mono text-[10px] leading-4 text-ink-400"
          dateTime={createdAt || undefined}
          title={timestamp}
        >
          {createdAt ? formatTimeAgo(createdAt) : timestamp}
        </time>
      </header>
      <div className={isPrivate ? "bg-[var(--color-warning-soft)] p-4 sm:p-5" : "p-4 sm:p-5"}>
        {isPrivate && (
          <p className="mb-3 inline-flex items-center gap-1.5 rounded-full border border-amber-400/30 bg-white/70 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-semantic-warning">
            <LockKeyhole className="h-3 w-3" aria-hidden="true" />
            Private note
          </p>
        )}
        <p className="break-words whitespace-pre-wrap text-sm leading-6 text-ink-600">
          {body || (isOriginal ? "No description was provided for this ticket." : "[Empty reply]")}
        </p>
        <AttachmentList ticketId={attachments[0]?.ticket_id || ""} attachments={attachments} />
      </div>
    </article>
  );
}

function formatBytes(value: number | null) {
  if (value == null) return "Size unavailable";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function AttachmentList({ ticketId, attachments }: { ticketId: string; attachments: TicketAttachment[] }) {
  if (attachments.length === 0) return null;
  return (
    <div className="mt-5 border-t border-linen-300 pt-4" aria-label="Synchronized attachments">
      <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-ink-500">
        <Paperclip className="h-3.5 w-3.5" aria-hidden="true" />
        {attachments.length} {attachments.length === 1 ? "attachment" : "attachments"}
      </p>
      <ul className="grid gap-2 sm:grid-cols-2">
        {attachments.map((attachment) => {
          const ready = attachment.status === "stored";
          const isImage = ready && ["image/png", "image/jpeg", "image/gif", "image/webp"].includes((attachment.content_type || "").toLowerCase());
          const href = `/api/tickets/${encodeURIComponent(ticketId)}/attachments/${encodeURIComponent(attachment.id)}`;
          return (
            <li key={attachment.id} className="overflow-hidden rounded-lg border border-linen-300 bg-linen-50">
              {isImage && (
                <a href={href} target="_blank" rel="noreferrer" className="block border-b border-linen-300 bg-white p-2">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={href} alt={attachment.name} loading="lazy" className="max-h-56 w-full rounded object-contain" />
                </a>
              )}
              <div className="flex items-center gap-2 p-2.5">
                {isImage ? <ImageIcon className="h-4 w-4 shrink-0 text-semantic-primary" /> : <Paperclip className="h-4 w-4 shrink-0 text-ink-400" />}
                <div className="min-w-0 flex-1">
                  <p className="whitespace-normal break-words text-xs font-medium text-ink-700 [overflow-wrap:anywhere]" title={attachment.name}>{attachment.name}</p>
                  <p className="mt-0.5 text-[10px] text-ink-400">{formatBytes(attachment.stored_size ?? attachment.size)}</p>
                </div>
                {ready ? (
                  <a href={href} download className="rounded p-1.5 text-semantic-primary hover:bg-linen-200" aria-label={`Download ${attachment.name}`}>
                    <Download className="h-4 w-4" />
                  </a>
                ) : (
                  <span className="rounded-full bg-linen-200 px-2 py-1 text-[10px] font-medium text-ink-500">
                    {attachment.status === "error" ? "Copy failed" : "Copy pending"}
                  </span>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function FreshserviceConversationThreadView({
  ticket,
  comments,
  attachments = [],
  loading,
  error,
  hasOlderReplies,
  loadingOlderReplies,
  onLoadOlderReplies,
  onRetry,
}: {
  ticket: ThreadTicket;
  comments: TicketComment[];
  attachments?: TicketAttachment[];
  loading: boolean;
  error: boolean;
  hasOlderReplies: boolean;
  loadingOlderReplies: boolean;
  onLoadOlderReplies: () => void;
  onRetry: () => void;
}) {
  const postCount = comments.length + 1;

  return (
    <section
      className="overflow-hidden rounded-2xl border border-linen-400 bg-linen-50 shadow-sm"
      aria-labelledby="freshservice-conversation-title"
    >
      <div className="flex flex-col gap-3 border-b border-linen-300 bg-gradient-to-r from-linen-100 to-white px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
        <div className="flex items-start gap-3">
          <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-[var(--color-primary-soft)] text-semantic-primary">
            <MessageSquareText className="h-[18px] w-[18px]" aria-hidden="true" />
          </div>
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-semantic-primary">Freshservice thread</p>
            <h2 id="freshservice-conversation-title" className="mt-0.5 text-lg font-semibold text-ink-700">Conversation</h2>
            <p className="mt-0.5 text-xs text-ink-500">The original request and synchronized replies, in chronological order.</p>
          </div>
        </div>
        <div className="flex items-center gap-2 self-start sm:self-auto">
          {!loading && <span className="text-xs text-ink-400">{postCount} {postCount === 1 ? "post" : "posts"} shown</span>}
          <span className="badge border-linen-400 bg-white text-ink-500">Read only</span>
        </div>
      </div>

      <ol className="space-y-3 p-3 sm:p-5" aria-label="Freshservice conversation posts">
        <li>
          <ThreadPost
            position={1}
            author={requesterName(ticket)}
            authorEmail={requesterEmail(ticket)}
            authorTitle={ticket.requester_title}
            authorType="requester"
            body={ticket.description}
            createdAt={ticket.external_created_at || ticket.created_at}
            isOriginal
            attachments={attachments.filter((attachment) => attachment.owner_type === "ticket")}
          />
        </li>

        {loading && (
          <li className="space-y-2" aria-label="Loading synchronized replies">
            <Skeleton className="h-28" />
            <Skeleton className="h-28" />
          </li>
        )}

        {error && (
          <li>
            <Alert
              variant="warning"
              title="Replies unavailable"
              action={<Button size="sm" variant="secondary" onClick={onRetry}>Retry</Button>}
            >
              The original request is shown, but synchronized replies could not be loaded.
            </Alert>
          </li>
        )}

        {!loading && hasOlderReplies && (
          <li className="flex justify-center py-1">
            <Button
              size="sm"
              variant="secondary"
              onClick={onLoadOlderReplies}
              pending={loadingOlderReplies}
              pendingLabel="Loading earlier replies…"
            >
              Load earlier replies
            </Button>
          </li>
        )}

        {comments.map((comment, index) => (
          <li key={comment.id}>
            <ThreadPost
              position={index + 2}
              author={comment.author_name}
              authorEmail={comment.author_email}
              authorTitle={comment.author_title}
              authorType={comment.author_type}
              body={comment.body}
              createdAt={comment.created_at}
              isPrivate={comment.is_private}
              attachments={attachments.filter((attachment) => (
                attachment.owner_type === "conversation"
                && attachment.owner_external_id === comment.external_id
              ))}
            />
          </li>
        ))}

        {!loading && !error && comments.length === 0 && (
          <li className="rounded-xl border border-dashed border-linen-400 px-4 py-6 text-center text-xs text-ink-400">
            No replies have been synchronized yet.
          </li>
        )}
      </ol>
    </section>
  );
}

export function FreshserviceConversationThread({ ticket }: { ticket: ThreadTicket }) {
  const commentsQuery = useInfiniteQuery({
    queryKey: ["ticket-comments", "freshservice-thread", ticket.id],
    queryFn: ({ pageParam }) => api.getComments(ticket.id, {
      limit: COMMENT_PAGE_SIZE,
      offset: pageParam,
    }),
    initialPageParam: 0,
    getNextPageParam: (lastPage, _pages, lastPageParam) => (
      lastPage.length === COMMENT_PAGE_SIZE
        ? lastPageParam + COMMENT_PAGE_SIZE
        : undefined
    ),
  });
  const comments = commentsQuery.data
    ? mergeChronologicalCommentPages(commentsQuery.data.pages)
    : [];
  const attachmentsQuery = useInfiniteQuery({
    queryKey: ["ticket-attachments", ticket.id],
    queryFn: async () => api.getAttachments(ticket.id),
    initialPageParam: 0,
    getNextPageParam: () => undefined,
  });

  return (
    <FreshserviceConversationThreadView
      ticket={ticket}
      comments={comments}
      attachments={attachmentsQuery.data?.pages[0] || []}
      loading={commentsQuery.isLoading}
      error={commentsQuery.isError}
      hasOlderReplies={commentsQuery.hasNextPage}
      loadingOlderReplies={commentsQuery.isFetchingNextPage}
      onLoadOlderReplies={() => void commentsQuery.fetchNextPage()}
      onRetry={() => void commentsQuery.refetch()}
    />
  );
}
