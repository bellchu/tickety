"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { KbArticle, KbArticleCreateInput } from "@/lib/types";
import {
  BookOpen, Plus, RefreshCw, Search, Eye, ThumbsUp, ThumbsDown,
  X, FileText, Tag, Trash2, Edit3, ChevronRight,
} from "lucide-react";
import { cn, formatTimeAgo } from "@/lib/utils";

export default function KnowledgeBasePage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [selected, setSelected] = useState<KbArticle | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<KbArticle | null>(null);

  const { data: articles, isLoading } = useQuery({
    queryKey: ["kb-articles", search, categoryFilter],
    queryFn: () => api.getKbArticles(search || undefined, categoryFilter || undefined),
  });

  const { data: catData } = useQuery({ queryKey: ["kb-categories"], queryFn: api.getKbCategories });
  const categories = catData?.categories || [];

  const createMut = useMutation({
    mutationFn: (payload: KbArticleCreateInput) => api.createKbArticle(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["kb-articles"] });
      queryClient.invalidateQueries({ queryKey: ["kb-categories"] });
      setShowForm(false);
    },
  });

  const updateMut = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Partial<KbArticleCreateInput> }) => api.updateKbArticle(id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["kb-articles"] });
      setEditing(null);
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => api.deleteKbArticle(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["kb-articles"] }),
  });

  const feedbackMut = useMutation({
    mutationFn: ({ id, helpful }: { id: string; helpful: boolean }) => api.kbFeedback(id, helpful),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["kb-articles"] }),
  });

  const list = articles || [];
  const published = list.filter((a) => a.status === "published");

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div className="space-y-1.5">
          <h1 className="font-serif text-3xl text-ink-700">Knowledge Base</h1>
          <p className="text-[13px] text-ink-500">
            {published.length} published articles · self-service guides and solutions
          </p>
        </div>
        <button onClick={() => setShowForm(true)} className="btn-primary text-xs">
          <Plus className="w-4 h-4" strokeWidth={1.5} />
          New Article
        </button>
      </div>

      {/* Search + filters */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1">
          <Search className="w-4 h-4 text-ink-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="Search articles…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="input-base pl-10"
          />
        </div>
        <select value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)} className="input-base w-48">
          <option value="">All categories</option>
          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>

      {/* Article list */}
      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">{[1, 2, 3, 4].map((i) => <div key={i} className="card-surface p-5"><div className="skeleton h-6 w-3/4 mb-3" /><div className="skeleton h-4 w-full mb-2" /><div className="skeleton h-4 w-1/2" /></div>)}</div>
      ) : list.length === 0 ? (
        <div className="card-surface p-12 text-center">
          <BookOpen className="w-10 h-10 text-ink-300 mx-auto mb-3" />
          <p className="text-ink-500">No articles found. Create your first KB article.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {list.map((a) => (
            <div
              key={a.id}
              className="card-surface p-5 cursor-pointer hover:border-linen-400 transition-colors group"
              onClick={() => setSelected(a)}
            >
              <div className="flex items-start justify-between gap-3 mb-2">
                <div className="flex items-center gap-2">
                  <FileText className="w-4 h-4 text-ink-400 shrink-0" />
                  <h3 className="text-sm font-semibold text-ink-700 group-hover:text-ink-800">{a.title}</h3>
                </div>
                {a.status !== "published" && (
                  <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold border border-amber-400/30 bg-amber-400/10 text-amber-600 shrink-0">
                    {a.status}
                  </span>
                )}
              </div>
              <p className="text-xs text-ink-400 line-clamp-2 mb-3">
                {a.content.replace(/[#*]/g, "").slice(0, 150)}…
              </p>
              <div className="flex items-center gap-3 text-[11px] text-ink-400">
                {a.category && (
                  <span className="inline-flex items-center gap-1">
                    <Tag className="w-3 h-3" /> {a.category}
                  </span>
                )}
                <span className="inline-flex items-center gap-1">
                  <Eye className="w-3 h-3" /> {a.views}
                </span>
                <span className="inline-flex items-center gap-1">
                  <ThumbsUp className="w-3 h-3" /> {a.helpful}
                </span>
                <span className="ml-auto">{formatTimeAgo(a.updated_at)}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Article reader modal */}
      {selected && (
        <ArticleReaderModal
          article={selected}
          onClose={() => setSelected(null)}
          onFeedback={(helpful) => feedbackMut.mutate({ id: selected.id, helpful })}
        />
      )}

      {/* Create / Edit modal */}
      {(showForm || editing) && (
        <ArticleFormModal
          article={editing}
          categories={categories}
          onClose={() => { setShowForm(false); setEditing(null); }}
          onSubmit={(payload) => {
            if (editing) {
              updateMut.mutate({ id: editing.id, payload });
            } else {
              createMut.mutate(payload);
            }
          }}
          loading={createMut.isPending || updateMut.isPending}
        />
      )}
    </div>
  );
}

function ArticleReaderModal({ article, onClose, onFeedback }: {
  article: KbArticle;
  onClose: () => void;
  onFeedback: (helpful: boolean) => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-800/30 backdrop-blur-sm p-4" onClick={onClose}>
      <div className="card-surface w-full max-w-2xl p-6 space-y-4 max-h-[85vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            {article.category && (
              <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold border border-linen-400 text-ink-500">
                {article.category}
              </span>
            )}
            {article.status !== "published" && (
              <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold border border-amber-400/30 bg-amber-400/10 text-amber-600">
                {article.status}
              </span>
            )}
          </div>
          <button onClick={onClose} className="p-1 rounded text-ink-400 hover:bg-linen-200"><X className="w-4 h-4" /></button>
        </div>
        <h2 className="font-serif text-2xl text-ink-700">{article.title}</h2>
        {article.tags && (
          <div className="flex items-center gap-1.5 flex-wrap">
            {article.tags.split(",").map((t) => (
              <span key={t} className="text-[11px] text-ink-400 bg-linen-200 px-2 py-0.5 rounded">#{t.trim()}</span>
            ))}
          </div>
        )}
        <div className="prose prose-sm max-w-none">
          <pre className="whitespace-pre-wrap font-sans text-sm text-ink-600 leading-relaxed bg-transparent p-0 border-0">
            {article.content}
          </pre>
        </div>
        <div className="border-t border-linen-300 pt-4 flex items-center justify-between">
          <span className="text-xs text-ink-400">{article.views} views · Updated {formatTimeAgo(article.updated_at)}</span>
          <div className="flex items-center gap-2">
            <span className="text-xs text-ink-500 mr-1">Was this helpful?</span>
            <button onClick={() => onFeedback(true)} className="inline-flex items-center gap-1 px-3 py-1.5 rounded border border-linen-400 text-xs text-ink-600 hover:bg-moss-400/10 hover:border-moss-400">
              <ThumbsUp className="w-3.5 h-3.5" /> Yes ({article.helpful})
            </button>
            <button onClick={() => onFeedback(false)} className="inline-flex items-center gap-1 px-3 py-1.5 rounded border border-linen-400 text-xs text-ink-600 hover:bg-rust-400/10 hover:border-rust-400">
              <ThumbsDown className="w-3.5 h-3.5" /> No ({article.not_helpful})
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function ArticleFormModal({ article, categories, onClose, onSubmit, loading }: {
  article: KbArticle | null;
  categories: string[];
  onClose: () => void;
  onSubmit: (payload: KbArticleCreateInput) => void;
  loading: boolean;
}) {
  const [title, setTitle] = useState(article?.title || "");
  const [content, setContent] = useState(article?.content || "");
  const [category, setCategory] = useState(article?.category || "");
  const [tags, setTags] = useState(article?.tags || "");
  const [status, setStatus] = useState(article?.status || "draft");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-800/30 backdrop-blur-sm p-4" onClick={onClose}>
      <div className="card-surface w-full max-w-2xl p-6 space-y-4 max-h-[85vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h2 className="font-serif text-xl text-ink-700">{article ? "Edit Article" : "New Article"}</h2>
          <button onClick={onClose} className="p-1 rounded text-ink-400 hover:bg-linen-200"><X className="w-4 h-4" /></button>
        </div>
        <label className="block space-y-1">
          <span className="text-xs font-medium text-ink-500">Title</span>
          <input value={title} onChange={(e) => setTitle(e.target.value)} className="input-base" placeholder="How to…" />
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="block space-y-1">
            <span className="text-xs font-medium text-ink-500">Category</span>
            <input list="kb-cat-list" value={category} onChange={(e) => setCategory(e.target.value)} className="input-base" placeholder="Network, Software…" />
            <datalist id="kb-cat-list">{categories.map((c) => <option key={c} value={c} />)}</datalist>
          </label>
          <label className="block space-y-1">
            <span className="text-xs font-medium text-ink-500">Tags (comma-separated)</span>
            <input value={tags} onChange={(e) => setTags(e.target.value)} className="input-base" placeholder="vpn, network" />
          </label>
        </div>
        <label className="block space-y-1">
          <span className="text-xs font-medium text-ink-500">Content (Markdown supported)</span>
          <textarea value={content} onChange={(e) => setContent(e.target.value)} rows={12} className="input-base font-mono text-xs resize-y" placeholder="Write your article…" />
        </label>
        <label className="block space-y-1">
          <span className="text-xs font-medium text-ink-500">Status</span>
          <select value={status} onChange={(e) => setStatus(e.target.value)} className="input-base">
            <option value="draft">Draft</option>
            <option value="published">Published</option>
            <option value="archived">Archived</option>
          </select>
        </label>
        <div className="flex items-center justify-end gap-2">
          <button onClick={onClose} className="px-3 py-2 rounded text-xs text-ink-500 hover:bg-linen-200">Cancel</button>
          <button
            onClick={() => onSubmit({ title, content, category: category || undefined, tags: tags || undefined, status })}
            disabled={loading || !title.trim()}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-ink-700 text-white text-xs font-semibold hover:bg-ink-800 disabled:opacity-50"
          >
            {loading && <RefreshCw className="w-3 h-3 animate-spin" />}
            {article ? "Save" : "Publish"}
          </button>
        </div>
      </div>
    </div>
  );
}