"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { LockKeyhole, MessageSquareText } from "lucide-react";
import { api } from "@/lib/api";
import type { Ticket, TicketComment } from "@/lib/types";
import { formatTimeAgo } from "@/lib/utils";
import { Alert, Button, Skeleton } from "@/components/ui";

const COMMENT_PAGE_SIZE = 500;

type ThreadTicket = Pick<
  Ticket,
  "id" | "description" | "reporter" | "created_at" | "external_created_at"
>;

export function formatThreadTimestamp(value: string | null): string {
  if (!value) return "Date unavailable";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Date unavailable";
  return `${date.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

export function mergeChronologicalCommentPages(
  pages: TicketComment[][],
): TicketComment[] {
  return [...pages].reverse().flat();
}

function ThreadPost({
  position,
  author,
  body,
  createdAt,
  isOriginal = false,
  isPrivate = false,
}: {
  position: number;
  author: string;
  body: string;
  createdAt: string | null;
  isOriginal?: boolean;
  isPrivate?: boolean;
}) {
  const timestamp = formatThreadTimestamp(createdAt);

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
      </div>
    </article>
  );
}

export function FreshserviceConversationThreadView({
  ticket,
  comments,
  loading,
  error,
  hasOlderReplies,
  loadingOlderReplies,
  onLoadOlderReplies,
  onRetry,
}: {
  ticket: ThreadTicket;
  comments: TicketComment[];
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
            author={ticket.reporter || "Requester"}
            body={ticket.description}
            createdAt={ticket.external_created_at || ticket.created_at}
            isOriginal
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
              body={comment.body}
              createdAt={comment.created_at}
              isPrivate={comment.is_private}
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

  return (
    <FreshserviceConversationThreadView
      ticket={ticket}
      comments={comments}
      loading={commentsQuery.isLoading}
      error={commentsQuery.isError}
      hasOlderReplies={commentsQuery.hasNextPage}
      loadingOlderReplies={commentsQuery.isFetchingNextPage}
      onLoadOlderReplies={() => void commentsQuery.fetchNextPage()}
      onRetry={() => void commentsQuery.refetch()}
    />
  );
}
