"use client";

import { useState } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Edit3, Eye, FileText, Plus, Search, Tag, ThumbsDown, ThumbsUp, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { canAccessProtectedIntelligence } from "@/lib/auth";
import type { KbArticle, KbArticleCreateInput } from "@/lib/types";
import { formatTimeAgo } from "@/lib/utils";
import { Badge, type BadgeVariant } from "@/components/ui/Badge";
import { Button, IconButton } from "@/components/ui/Button";
import { ConfirmDialog, Dialog } from "@/components/ui/Dialog";
import { Alert, EmptyState, ErrorState, Skeleton } from "@/components/ui/Feedback";
import { ListText } from "@/components/ui";
import { PageFrame, PageHeader } from "@/components/layout/PageLayout";

const articleVariant = (status: string): BadgeVariant => status === "published" ? "success" : status === "archived" ? "neutral" : "warning";

export default function KnowledgeBasePage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<"" | "published" | "draft" | "archived">("");
  const [selected, setSelected] = useState<KbArticle | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<KbArticle | null>(null);
  const [deleting, setDeleting] = useState<KbArticle | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const meQuery = useQuery({ queryKey: ["auth-me"], queryFn: api.getAuthMe, retry: false });
  const canManage = canAccessProtectedIntelligence(meQuery.data);
  const serverStatus = canManage ? (statusFilter || "all") : "published";
  const articlesQuery = useInfiniteQuery({
    queryKey: ["kb-articles", search, categoryFilter, serverStatus],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => api.getKbArticles({
      search: search || undefined,
      category: categoryFilter || undefined,
      status: serverStatus,
      limit: 20,
      offset: pageParam,
    }),
    getNextPageParam: (lastPage) => lastPage.hasMore
      ? lastPage.offset + lastPage.limit
      : undefined,
  });
  const categoriesQuery = useQuery({
    queryKey: ["kb-categories", canManage ? "all" : "published"],
    queryFn: () => api.getKbCategories(canManage),
    enabled: meQuery.isSuccess,
  });
  const refreshKnowledge = async () => { await Promise.all([queryClient.invalidateQueries({ queryKey: ["kb-articles"] }), queryClient.invalidateQueries({ queryKey: ["kb-categories"] })]); };

  const createMut = useMutation({
    mutationFn: (payload: KbArticleCreateInput) => api.createKbArticle(payload),
    onSuccess: async (article) => { await refreshKnowledge(); setShowForm(false); setNotice(article.status === "published" ? "Article published to the knowledge base." : "Draft article created."); },
  });
  const updateMut = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Partial<KbArticleCreateInput> }) => api.updateKbArticle(id, payload),
    onSuccess: async (article) => { await refreshKnowledge(); setEditing(null); setSelected((current) => current?.id === article.id ? article : current); setNotice("Article changes saved."); },
  });
  const deleteMut = useMutation({
    mutationFn: (id: string) => api.deleteKbArticle(id),
    onSuccess: async () => { await refreshKnowledge(); setDeleting(null); setSelected(null); setNotice("Article removed from the knowledge base."); },
  });
  const feedbackMut = useMutation({
    mutationFn: ({ id, helpful }: { id: string; helpful: boolean }) => api.kbFeedback(id, helpful),
    onSuccess: async (_, variables) => { await queryClient.invalidateQueries({ queryKey: ["kb-articles"] }); setNotice(variables.helpful ? "Thanks — your feedback was recorded." : "Thanks — this article has been flagged for improvement."); setSelected(null); },
  });
  const readMut = useMutation({
    mutationFn: (id: string) => api.getKbArticle(id),
    onSuccess: async (article) => {
      setSelected(article);
      await queryClient.invalidateQueries({ queryKey: ["kb-articles"] });
    },
  });

  const articles = articlesQuery.data?.pages.flatMap((page) => page.articles) ?? [];
  const visibleArticles = articles;
  const categories = categoriesQuery.data?.categories ?? [];
  const hasFilters = Boolean(search || categoryFilter || statusFilter);
  const actionError = deleteMut.error || feedbackMut.error || readMut.error;
  const actionErrorMessage = actionError instanceof Error
    ? actionError.message
    : "Could not load categories or complete the requested action.";

  return <PageFrame width="wide">
    <PageHeader eyebrow="Self-service operations" icon={<BookOpen className="h-4 w-4" />} title="Knowledge base" description="Turn proven resolutions into clear, trusted guidance for requesters and support teams." actions={canManage ? <Button leadingIcon={<Plus className="h-4 w-4" />} onClick={() => { setNotice(null); setShowForm(true); }}>New article</Button> : undefined} />

    {notice && <Alert variant="success" title="Knowledge base updated">{notice}</Alert>}
    {(deleteMut.isError || feedbackMut.isError || readMut.isError || categoriesQuery.isError) && <Alert variant="danger" title="Some knowledge actions are unavailable">{actionErrorMessage}</Alert>}

    {canManage && <div className="flex flex-wrap gap-2" aria-label="Article publication status">
      {([{"value":"","label":"All"},{"value":"published","label":"Published"},{"value":"draft","label":"Drafts"},{"value":"archived","label":"Archived"}] as const).map((view) => <button key={view.value || "all"} type="button" aria-pressed={statusFilter === view.value} onClick={() => setStatusFilter(view.value)} className={`min-h-11 rounded-full border px-3 text-xs font-semibold transition-colors sm:min-h-9 ${statusFilter === view.value ? "border-clay-300 bg-[var(--color-primary-soft)] text-semantic-primary" : "border-linen-400 bg-linen-50 text-ink-500 hover:bg-linen-200"}`}>{view.label}</button>)}
    </div>}

    <section aria-labelledby="library-heading" className="space-y-4"><div className="flex flex-col gap-3 lg:flex-row lg:items-end"><div className="min-w-0 flex-1"><h2 id="library-heading" className="text-lg font-semibold text-ink-700">Article library</h2><p className="mt-1 text-xs text-ink-400" aria-live="polite">{articlesQuery.isLoading ? "Loading articles…" : `${visibleArticles.length} article${visibleArticles.length === 1 ? "" : "s"} loaded${articlesQuery.hasNextPage ? "; more available" : ""}`}</p></div><label className="relative block min-w-0 flex-1 lg:max-w-md"><span className="sr-only">Search knowledge articles</span><Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" aria-hidden="true" /><input type="search" className="input-base input-search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search titles and content…" /></label><label className="lg:w-56"><span className="sr-only">Filter articles by category</span><select className="input-base" value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}><option value="">All categories</option>{categories.map((category) => <option key={category}>{category}</option>)}</select></label></div>
      {articlesQuery.isLoading ? <ArticleSkeleton /> : articlesQuery.isError && !visibleArticles.length ? <ErrorState title="Could not load knowledge articles" description="Search and article management are temporarily unavailable." onRetry={() => articlesQuery.refetch()} retrying={articlesQuery.isFetching} /> : visibleArticles.length === 0 ? <EmptyState icon={<BookOpen className="h-5 w-5" />} title={hasFilters ? "No articles match this view" : "No knowledge articles yet"} description={hasFilters ? "Try a broader search or clear the current filters." : "Capture the first proven resolution so the next requester can self-serve."} action={hasFilters ? <Button variant="secondary" onClick={() => { setSearch(""); setCategoryFilter(""); setStatusFilter(""); }}>Clear filters</Button> : canManage ? <Button leadingIcon={<Plus className="h-4 w-4" />} onClick={() => setShowForm(true)}>New article</Button> : undefined} /> : <><div className="grid gap-4 lg:grid-cols-2">{visibleArticles.map((article) => <ArticleCard key={article.id} article={article} canManage={canManage} reading={readMut.isPending && readMut.variables === article.id} onRead={(item) => readMut.mutate(item.id)} onEdit={setEditing} onDelete={setDeleting} />)}</div>{articlesQuery.isFetchNextPageError && <Alert variant="danger" title="More articles could not be loaded" action={<Button size="sm" variant="secondary" onClick={() => void articlesQuery.fetchNextPage()}>Retry</Button>}>The articles already shown remain available.</Alert>}{articlesQuery.hasNextPage && !articlesQuery.isFetchNextPageError && <div className="flex justify-center pt-2"><Button variant="secondary" onClick={() => void articlesQuery.fetchNextPage()} pending={articlesQuery.isFetchingNextPage} pendingLabel="Loading more…">Load 20 more</Button></div>}</>}
    </section>

    <ArticleReaderDialog open={Boolean(selected)} article={selected} canManage={canManage} onClose={() => { if (!feedbackMut.isPending) { setSelected(null); feedbackMut.reset(); } }} onEdit={(article) => { setSelected(null); setEditing(article); }} onDelete={(article) => { setSelected(null); setDeleting(article); }} onFeedback={(helpful) => selected && feedbackMut.mutate({ id: selected.id, helpful })} pending={feedbackMut.isPending} error={feedbackMut.error} />
    {canManage && <ArticleFormDialog open={showForm || Boolean(editing)} article={editing} categories={categories} onClose={() => { if (!createMut.isPending && !updateMut.isPending) { setShowForm(false); setEditing(null); createMut.reset(); updateMut.reset(); } }} onSubmit={(payload) => editing ? updateMut.mutate({ id: editing.id, payload }) : createMut.mutate(payload)} pending={createMut.isPending || updateMut.isPending} error={createMut.error || updateMut.error} />}
    {canManage && <ConfirmDialog open={Boolean(deleting)} onOpenChange={(open) => { if (!open) { setDeleting(null); deleteMut.reset(); } }} title="Delete article?" description={<>This permanently removes <strong>{deleting?.title}</strong> and its feedback history. This action cannot be undone.</>} confirmLabel="Delete article" destructive pending={deleteMut.isPending} onConfirm={() => { if (deleting) deleteMut.mutate(deleting.id); }} />}
  </PageFrame>;
}
function ArticleSkeleton() { return <div className="grid gap-4 lg:grid-cols-2" aria-label="Loading knowledge articles">{Array.from({ length: 4 }, (_, i) => <div key={i} className="card-surface p-5"><Skeleton className="h-5 w-3/4" /><Skeleton className="mt-4 h-4 w-full" /><Skeleton className="mt-2 h-4 w-2/3" /><Skeleton className="mt-5 h-6 w-1/3" /></div>)}</div>; }

function articleExcerpt(content: string, limit = 240) {
  const clean = content.replace(/[#*_`]/g, " ").replace(/\s+/g, " ").trim();
  if (!clean) return "No article content yet.";
  if (clean.length <= limit) return clean;
  const candidate = clean.slice(0, limit + 1);
  const lastBoundary = Math.max(candidate.lastIndexOf(" "), candidate.lastIndexOf("."));
  return `${candidate.slice(0, lastBoundary > limit * 0.6 ? lastBoundary : limit).trimEnd()}…`;
}

function ArticleCard({ article, canManage, reading, onRead, onEdit, onDelete }: { article: KbArticle; canManage: boolean; reading: boolean; onRead: (article: KbArticle) => void; onEdit: (article: KbArticle) => void; onDelete: (article: KbArticle) => void }) {
  const summary = articleExcerpt(article.content);
  return <article className="card-surface group flex min-h-56 min-w-0 flex-col p-5 transition-[border-color,box-shadow] hover:border-linen-500 hover:shadow-sm"><div className="flex min-w-0 items-start gap-3"><div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-[var(--color-primary-soft)] text-semantic-primary"><FileText className="h-5 w-5" aria-hidden="true" /></div><div className="min-w-0 flex-1"><div className="flex min-w-0 flex-wrap items-center gap-2"><Badge variant={articleVariant(article.status)} dot>{article.status}</Badge>{article.category && <Badge icon={<Tag className="h-3 w-3" />}>{article.category}</Badge>}</div><h3 className="mt-3"><ListText text={article.title} lines={2} className="overflow-hidden text-base font-semibold leading-6 text-ink-700 [display:-webkit-box] [-webkit-box-orient:vertical] [-webkit-line-clamp:2]" /></h3></div></div><ListText text={summary} lines={3} className="mt-4 overflow-hidden text-sm leading-6 text-ink-500 [display:-webkit-box] [-webkit-box-orient:vertical] [-webkit-line-clamp:3]" /><div className="mt-auto border-t border-linen-200 pt-4 text-xs text-ink-400"><div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2"><span className="inline-flex items-center gap-1"><Eye className="h-3.5 w-3.5" aria-hidden="true" /> {article.views}</span><span className="inline-flex items-center gap-1"><ThumbsUp className="h-3.5 w-3.5" aria-hidden="true" /> {article.helpful}</span><span className="min-w-0">{article.updated_at ? `Updated ${formatTimeAgo(article.updated_at)}` : "Not yet updated"}</span></div><div className="mt-3 flex flex-wrap justify-end gap-1">{canManage && <><IconButton size="sm" aria-label={`Edit ${article.title}`} icon={<Edit3 className="h-4 w-4" />} onClick={() => onEdit(article)} /><IconButton size="sm" aria-label={`Delete ${article.title}`} icon={<Trash2 className="h-4 w-4" />} onClick={() => onDelete(article)} /></>}<Button size="sm" variant="secondary" onClick={() => onRead(article)} pending={reading} pendingLabel="Opening…">Read</Button></div></div></article>;
}

function ArticleReaderDialog({ open, article, canManage, onClose, onEdit, onDelete, onFeedback, pending, error }: { open: boolean; article: KbArticle | null; canManage: boolean; onClose: () => void; onEdit: (article: KbArticle) => void; onDelete: (article: KbArticle) => void; onFeedback: (helpful: boolean) => void; pending: boolean; error: unknown }) {
  if (!article) return null;
  const published = article.status === "published";
  return <Dialog open={open} onOpenChange={(next) => { if (!next) onClose(); }} title={article.title} description={<span className="flex flex-wrap items-center gap-2"><Badge variant={articleVariant(article.status)}>{article.status}</Badge>{article.category && <Badge>{article.category}</Badge>}<span>{article.views} views · v{article.version}</span></span>} className="max-w-3xl" dismissible={!pending} footer={<>{canManage && <><Button variant="ghost" leadingIcon={<Trash2 className="h-4 w-4" />} onClick={() => onDelete(article)} disabled={pending}>Delete</Button><Button variant="secondary" leadingIcon={<Edit3 className="h-4 w-4" />} onClick={() => onEdit(article)} disabled={pending}>Edit article</Button></>}{published && <><Button variant="secondary" leadingIcon={<ThumbsDown className="h-4 w-4" />} onClick={() => onFeedback(false)} disabled={pending}>Needs work</Button><Button leadingIcon={<ThumbsUp className="h-4 w-4" />} onClick={() => onFeedback(true)} pending={pending} pendingLabel="Recording…">Helpful</Button></>}</>}><div className="space-y-5">{error ? <Alert variant="danger" title="Feedback was not recorded">{error instanceof Error ? error.message : "Please try again."}</Alert> : null}{article.tags && <div className="flex flex-wrap gap-2" aria-label="Article tags">{article.tags.split(",").map((tag) => tag.trim()).filter(Boolean).map((tag) => <Badge key={tag}>#{tag}</Badge>)}</div>}<div className="whitespace-pre-wrap break-words text-sm leading-7 text-ink-600 [overflow-wrap:anywhere]">{article.content}</div><div className="break-words border-t border-linen-300 pt-4 text-xs text-ink-400 [overflow-wrap:anywhere]">{article.author_name ? `Written by ${article.author_name}` : "Author not recorded"}{article.updated_at ? ` · Updated ${formatTimeAgo(article.updated_at)}` : ""}</div></div></Dialog>;
}

function ArticleFormDialog({ open, article, categories, onClose, onSubmit, pending, error }: { open: boolean; article: KbArticle | null; categories: string[]; onClose: () => void; onSubmit: (payload: KbArticleCreateInput) => void; pending: boolean; error: unknown }) { const key = article?.id ?? (open ? "new" : "closed"); return <ArticleFormDialogBody key={key} {...{ open, article, categories, onClose, onSubmit, pending, error }} />; }
function ArticleFormDialogBody({ open, article, categories, onClose, onSubmit, pending, error }: { open: boolean; article: KbArticle | null; categories: string[]; onClose: () => void; onSubmit: (payload: KbArticleCreateInput) => void; pending: boolean; error: unknown }) {
  const [form, setForm] = useState({ title: article?.title || "", content: article?.content || "", category: article?.category || "", tags: article?.tags || "", status: article?.status || "draft" });
  const set = (key: keyof typeof form, value: string) => setForm((current) => ({ ...current, [key]: value }));
  const errorMessage = error instanceof Error ? error.message : error ? "The article could not be saved." : null;
  const valid = Boolean(form.title.trim() && form.content.trim());
  return <Dialog open={open} onOpenChange={(next) => { if (!next) onClose(); }} title={article ? "Edit article" : "New knowledge article"} description="Write clear guidance as a draft. Publication requires review by a different admin or supervisor." className="max-w-3xl" dismissible={!pending} footer={<><Button variant="secondary" onClick={onClose} disabled={pending}>Cancel</Button><Button pending={pending} pendingLabel="Saving…" disabled={!valid} onClick={() => onSubmit({ title: form.title.trim(), content: form.content.trim(), category: form.category || undefined, tags: form.tags || undefined, status: form.status })}>{form.status === "published" ? "Publish reviewed article" : article ? "Save draft" : "Create draft"}</Button></>}><div className="space-y-4">{errorMessage && <Alert variant="danger" title="Could not save article">{errorMessage}</Alert>}<Field label="Title"><input className="input-base" value={form.title} onChange={(e) => set("title", e.target.value)} placeholder="How to restore VPN access" /></Field><div className="grid gap-4 sm:grid-cols-2"><Field label="Category"><input className="input-base" list="kb-categories" value={form.category} onChange={(e) => set("category", e.target.value)} placeholder="Network" /><datalist id="kb-categories">{categories.map((category) => <option key={category} value={category} />)}</datalist></Field><Field label="Tags"><input className="input-base" value={form.tags} onChange={(e) => set("tags", e.target.value)} placeholder="vpn, access, remote" /></Field></div><Field label="Content"><textarea className="input-base min-h-72 resize-y font-mono text-xs leading-6" value={form.content} onChange={(e) => set("content", e.target.value)} placeholder="Describe symptoms, prerequisites, safe steps, verification, and escalation guidance…" /></Field><Field label="Publication status"><select className="input-base" value={form.status} onChange={(e) => set("status", e.target.value)}><option value="draft">Draft</option>{article && <option value="published">Published (independent review)</option>}<option value="archived">Archived</option></select></Field></div></Dialog>;
}
function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="block"><span className="mb-1.5 block text-xs font-semibold text-ink-500">{label}</span>{children}</label>; }
