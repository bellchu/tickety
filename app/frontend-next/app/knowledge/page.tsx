"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Edit3, Eye, FileText, Plus, Search, Tag, ThumbsDown, ThumbsUp, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import type { KbArticle, KbArticleCreateInput } from "@/lib/types";
import { formatTimeAgo } from "@/lib/utils";
import { Badge, type BadgeVariant } from "@/components/ui/Badge";
import { Button, IconButton } from "@/components/ui/Button";
import { ConfirmDialog, Dialog } from "@/components/ui/Dialog";
import { Alert, EmptyState, ErrorState, Skeleton } from "@/components/ui/Feedback";

const articleVariant = (status: string): BadgeVariant => status === "published" ? "success" : status === "archived" ? "neutral" : "warning";

export default function KnowledgeBasePage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [selected, setSelected] = useState<KbArticle | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<KbArticle | null>(null);
  const [deleting, setDeleting] = useState<KbArticle | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const articlesQuery = useQuery({ queryKey: ["kb-articles", search, categoryFilter], queryFn: () => api.getKbArticles(search || undefined, categoryFilter || undefined) });
  const categoriesQuery = useQuery({ queryKey: ["kb-categories"], queryFn: api.getKbCategories });
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

  const articles = articlesQuery.data ?? [];
  const categories = categoriesQuery.data?.categories ?? [];
  const published = articles.filter((article) => article.status === "published");
  const totalViews = articles.reduce((sum, article) => sum + article.views, 0);
  const helpfulTotal = articles.reduce((sum, article) => sum + article.helpful, 0);
  const feedbackTotal = articles.reduce((sum, article) => sum + article.helpful + article.not_helpful, 0);
  const helpfulRate = feedbackTotal ? Math.round((helpfulTotal / feedbackTotal) * 100) : 0;
  const hasFilters = Boolean(search || categoryFilter);
  const actionError = deleteMut.error || feedbackMut.error;
  const actionErrorMessage = actionError instanceof Error
    ? actionError.message
    : "Could not load categories or complete the requested action.";

  return <div className="space-y-8">
    <header className="flex flex-col gap-4 border-b border-linen-300 pb-6 sm:flex-row sm:items-end sm:justify-between"><div><div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-ink-400"><BookOpen className="h-4 w-4" aria-hidden="true" /> Self-service operations</div><h1 className="font-serif text-3xl tracking-tight text-ink-700 sm:text-4xl">Knowledge base</h1><p className="mt-2 max-w-2xl text-sm text-ink-500">Turn proven resolutions into clear, trusted guidance for requesters and support teams.</p></div><Button leadingIcon={<Plus className="h-4 w-4" />} onClick={() => { setNotice(null); setShowForm(true); }}>New article</Button></header>

    {notice && <Alert variant="success" title="Knowledge base updated">{notice}</Alert>}
    {(deleteMut.isError || feedbackMut.isError || categoriesQuery.isError) && <Alert variant="danger" title="Some knowledge actions are unavailable">{actionErrorMessage}</Alert>}

    <section aria-label="Knowledge base summary" className="grid grid-cols-2 gap-3 lg:grid-cols-4"><Metric label="Published" value={published.length} featured /><Metric label="Drafts" value={articles.filter((article) => article.status === "draft").length} /><Metric label="Article views" value={totalViews} /><Metric label="Helpful rating" value={`${helpfulRate}%`} /></section>

    <section aria-labelledby="library-heading" className="space-y-4"><div className="flex flex-col gap-3 lg:flex-row lg:items-end"><div className="min-w-0 flex-1"><h2 id="library-heading" className="text-lg font-semibold text-ink-700">Article library</h2><p className="mt-1 text-xs text-ink-400" aria-live="polite">{articlesQuery.isLoading ? "Loading articles…" : `${articles.length} matching article${articles.length === 1 ? "" : "s"}`}</p></div><label className="relative block min-w-0 flex-1 lg:max-w-md"><span className="sr-only">Search knowledge articles</span><Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" aria-hidden="true" /><input type="search" className="input-base input-search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search titles and content…" /></label><label className="lg:w-56"><span className="sr-only">Filter articles by category</span><select className="input-base" value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}><option value="">All categories</option>{categories.map((category) => <option key={category}>{category}</option>)}</select></label></div>
      {articlesQuery.isLoading ? <ArticleSkeleton /> : articlesQuery.isError ? <ErrorState title="Could not load knowledge articles" description="Search and article management are temporarily unavailable." onRetry={() => articlesQuery.refetch()} retrying={articlesQuery.isFetching} /> : articles.length === 0 ? <EmptyState icon={<BookOpen className="h-5 w-5" />} title={hasFilters ? "No articles match this search" : "No knowledge articles yet"} description={hasFilters ? "Try a broader search or clear the category filter." : "Capture the first proven resolution so the next requester can self-serve."} action={hasFilters ? <Button variant="secondary" onClick={() => { setSearch(""); setCategoryFilter(""); }}>Clear filters</Button> : <Button leadingIcon={<Plus className="h-4 w-4" />} onClick={() => setShowForm(true)}>New article</Button>} /> : <div className="grid gap-4 lg:grid-cols-2">{articles.map((article) => <ArticleCard key={article.id} article={article} onRead={setSelected} onEdit={setEditing} onDelete={setDeleting} />)}</div>}
    </section>

    <ArticleReaderDialog open={Boolean(selected)} article={selected} onClose={() => { if (!feedbackMut.isPending) { setSelected(null); feedbackMut.reset(); } }} onEdit={(article) => { setSelected(null); setEditing(article); }} onDelete={(article) => { setSelected(null); setDeleting(article); }} onFeedback={(helpful) => selected && feedbackMut.mutate({ id: selected.id, helpful })} pending={feedbackMut.isPending} error={feedbackMut.error} />
    <ArticleFormDialog open={showForm || Boolean(editing)} article={editing} categories={categories} onClose={() => { if (!createMut.isPending && !updateMut.isPending) { setShowForm(false); setEditing(null); createMut.reset(); updateMut.reset(); } }} onSubmit={(payload) => editing ? updateMut.mutate({ id: editing.id, payload }) : createMut.mutate(payload)} pending={createMut.isPending || updateMut.isPending} error={createMut.error || updateMut.error} />
    <ConfirmDialog open={Boolean(deleting)} onOpenChange={(open) => { if (!open) { setDeleting(null); deleteMut.reset(); } }} title="Delete article?" description={<>This permanently removes <strong>{deleting?.title}</strong> and its feedback history. This action cannot be undone.</>} confirmLabel="Delete article" destructive pending={deleteMut.isPending} onConfirm={() => { if (deleting) deleteMut.mutate(deleting.id); }} />
  </div>;
}

function Metric({ label, value, featured }: { label: string; value: number | string; featured?: boolean }) { return <div className={`rounded-2xl border p-4 ${featured ? "border-clay-200 bg-[var(--color-primary-soft)]" : "border-linen-300 bg-linen-50"}`}><p className="text-xs font-medium text-ink-500">{label}</p><p className="mt-2 font-serif text-3xl tabular-nums text-ink-700">{value}</p></div>; }
function ArticleSkeleton() { return <div className="grid gap-4 lg:grid-cols-2" aria-label="Loading knowledge articles">{Array.from({ length: 4 }, (_, i) => <div key={i} className="card-surface p-5"><Skeleton className="h-5 w-3/4" /><Skeleton className="mt-4 h-4 w-full" /><Skeleton className="mt-2 h-4 w-2/3" /><Skeleton className="mt-5 h-6 w-1/3" /></div>)}</div>; }

function ArticleCard({ article, onRead, onEdit, onDelete }: { article: KbArticle; onRead: (article: KbArticle) => void; onEdit: (article: KbArticle) => void; onDelete: (article: KbArticle) => void }) {
  return <article className="card-surface group flex min-h-56 flex-col p-5 transition-[border-color,box-shadow] hover:border-linen-500 hover:shadow-sm"><div className="flex items-start gap-3"><div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-[var(--color-primary-soft)] text-semantic-primary"><FileText className="h-5 w-5" aria-hidden="true" /></div><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><Badge variant={articleVariant(article.status)} dot>{article.status}</Badge>{article.category && <Badge icon={<Tag className="h-3 w-3" />}>{article.category}</Badge>}</div><h3 className="mt-3 text-base font-semibold leading-6 text-ink-700">{article.title}</h3></div></div><p className="mt-4 line-clamp-3 text-sm leading-6 text-ink-500">{article.content.replace(/[#*_`]/g, " ").replace(/\s+/g, " ").trim() || "No article content yet."}</p><div className="mt-auto flex flex-wrap items-center gap-3 border-t border-linen-200 pt-4 text-xs text-ink-400"><span className="inline-flex items-center gap-1"><Eye className="h-3.5 w-3.5" aria-hidden="true" /> {article.views}</span><span className="inline-flex items-center gap-1"><ThumbsUp className="h-3.5 w-3.5" aria-hidden="true" /> {article.helpful}</span><span>{article.updated_at ? `Updated ${formatTimeAgo(article.updated_at)}` : "Not yet updated"}</span><div className="ml-auto flex gap-1"><IconButton size="sm" aria-label={`Edit ${article.title}`} icon={<Edit3 className="h-4 w-4" />} onClick={() => onEdit(article)} /><IconButton size="sm" aria-label={`Delete ${article.title}`} icon={<Trash2 className="h-4 w-4" />} onClick={() => onDelete(article)} /><Button size="sm" variant="secondary" onClick={() => onRead(article)}>Read</Button></div></div></article>;
}

function ArticleReaderDialog({ open, article, onClose, onEdit, onDelete, onFeedback, pending, error }: { open: boolean; article: KbArticle | null; onClose: () => void; onEdit: (article: KbArticle) => void; onDelete: (article: KbArticle) => void; onFeedback: (helpful: boolean) => void; pending: boolean; error: unknown }) {
  if (!article) return null;
  return <Dialog open={open} onOpenChange={(next) => { if (!next) onClose(); }} title={article.title} description={<span className="flex flex-wrap items-center gap-2"><Badge variant={articleVariant(article.status)}>{article.status}</Badge>{article.category && <Badge>{article.category}</Badge>}<span>{article.views} views · v{article.version}</span></span>} className="max-w-3xl" dismissible={!pending} footer={<><Button variant="ghost" leadingIcon={<Trash2 className="h-4 w-4" />} onClick={() => onDelete(article)} disabled={pending}>Delete</Button><Button variant="secondary" leadingIcon={<Edit3 className="h-4 w-4" />} onClick={() => onEdit(article)} disabled={pending}>Edit article</Button><Button variant="secondary" leadingIcon={<ThumbsDown className="h-4 w-4" />} onClick={() => onFeedback(false)} disabled={pending}>Needs work</Button><Button leadingIcon={<ThumbsUp className="h-4 w-4" />} onClick={() => onFeedback(true)} pending={pending} pendingLabel="Recording…">Helpful</Button></>}><div className="space-y-5">{error ? <Alert variant="danger" title="Feedback was not recorded">{error instanceof Error ? error.message : "Please try again."}</Alert> : null}{article.tags && <div className="flex flex-wrap gap-2" aria-label="Article tags">{article.tags.split(",").map((tag) => tag.trim()).filter(Boolean).map((tag) => <Badge key={tag}>#{tag}</Badge>)}</div>}<div className="whitespace-pre-wrap text-sm leading-7 text-ink-600">{article.content}</div><div className="border-t border-linen-300 pt-4 text-xs text-ink-400">{article.author_name ? `Written by ${article.author_name}` : "Author not recorded"}{article.updated_at ? ` · Updated ${formatTimeAgo(article.updated_at)}` : ""}</div></div></Dialog>;
}

function ArticleFormDialog({ open, article, categories, onClose, onSubmit, pending, error }: { open: boolean; article: KbArticle | null; categories: string[]; onClose: () => void; onSubmit: (payload: KbArticleCreateInput) => void; pending: boolean; error: unknown }) { const key = article?.id ?? (open ? "new" : "closed"); return <ArticleFormDialogBody key={key} {...{ open, article, categories, onClose, onSubmit, pending, error }} />; }
function ArticleFormDialogBody({ open, article, categories, onClose, onSubmit, pending, error }: { open: boolean; article: KbArticle | null; categories: string[]; onClose: () => void; onSubmit: (payload: KbArticleCreateInput) => void; pending: boolean; error: unknown }) {
  const [form, setForm] = useState({ title: article?.title || "", content: article?.content || "", category: article?.category || "", tags: article?.tags || "", status: article?.status || "draft" });
  const set = (key: keyof typeof form, value: string) => setForm((current) => ({ ...current, [key]: value }));
  const errorMessage = error instanceof Error ? error.message : error ? "The article could not be saved." : null;
  const valid = Boolean(form.title.trim() && form.content.trim());
  return <Dialog open={open} onOpenChange={(next) => { if (!next) onClose(); }} title={article ? "Edit article" : "New knowledge article"} description="Write for a reader who is solving the issue for the first time. Use a draft until the guidance is verified." className="max-w-3xl" dismissible={!pending} footer={<><Button variant="secondary" onClick={onClose} disabled={pending}>Cancel</Button><Button pending={pending} pendingLabel="Saving…" disabled={!valid} onClick={() => onSubmit({ title: form.title.trim(), content: form.content.trim(), category: form.category || undefined, tags: form.tags || undefined, status: form.status })}>{form.status === "published" ? article ? "Save and publish" : "Publish article" : article ? "Save draft" : "Create draft"}</Button></>}><div className="space-y-4">{errorMessage && <Alert variant="danger" title="Could not save article">{errorMessage}</Alert>}<Field label="Title"><input className="input-base" value={form.title} onChange={(e) => set("title", e.target.value)} placeholder="How to restore VPN access" /></Field><div className="grid gap-4 sm:grid-cols-2"><Field label="Category"><input className="input-base" list="kb-categories" value={form.category} onChange={(e) => set("category", e.target.value)} placeholder="Network" /><datalist id="kb-categories">{categories.map((category) => <option key={category} value={category} />)}</datalist></Field><Field label="Tags"><input className="input-base" value={form.tags} onChange={(e) => set("tags", e.target.value)} placeholder="vpn, access, remote" /></Field></div><Field label="Content"><textarea className="input-base min-h-72 resize-y font-mono text-xs leading-6" value={form.content} onChange={(e) => set("content", e.target.value)} placeholder="Describe symptoms, prerequisites, safe steps, verification, and escalation guidance…" /></Field><Field label="Publication status"><select className="input-base" value={form.status} onChange={(e) => set("status", e.target.value)}><option value="draft">Draft</option><option value="published">Published</option><option value="archived">Archived</option></select></Field></div></Dialog>;
}
function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="block"><span className="mb-1.5 block text-xs font-semibold text-ink-500">{label}</span>{children}</label>; }
