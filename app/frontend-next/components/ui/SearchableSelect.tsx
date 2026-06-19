"use client";

import { useState, useRef, useEffect } from "react";
import { Search, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

interface Option {
  id: string;
  label: string;
}

interface Props {
  value: string;
  options: Option[];
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
}

export function SearchableSelect({
  value,
  options,
  onChange,
  placeholder = "Select or type a model…",
  disabled = false,
}: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlighted, setHighlighted] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const filtered = query
    ? options.filter(
        (o) =>
          o.id.toLowerCase().includes(query.toLowerCase()) ||
          o.label.toLowerCase().includes(query.toLowerCase())
      )
    : options;

  const selectedOption = options.find((o) => o.id === value);

  const select = (id: string) => {
    onChange(id);
    setOpen(false);
    setQuery("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlighted((h) => Math.min(h + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlighted((h) => Math.max(h - 1, 0));
    } else if (e.key === "Enter" && open && filtered[highlighted]) {
      e.preventDefault();
      select(filtered[highlighted].id);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  useEffect(() => {
    if (open && listRef.current) {
      const el = listRef.current.children[highlighted] as HTMLElement | undefined;
      el?.scrollIntoView({ block: "nearest" });
    }
  }, [highlighted, open]);

  // Plain text input for providers with no models at all
  if (options.length === 0) {
    return (
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="input-base"
        disabled={disabled}
      />
    );
  }

  return (
    <div ref={containerRef} className="relative">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
        <input
          ref={inputRef}
          type="text"
          value={open ? query : (selectedOption?.label || value)}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
            setHighlighted(0);
          }}
          onFocus={() => { setOpen(true); setQuery(""); }}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          className="input-base pl-9 pr-8"
          disabled={disabled}
        />
        <button
          type="button"
          onClick={() => { setOpen(!open); inputRef.current?.focus(); }}
          className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-slate-400 hover:text-slate-600"
        >
          <ChevronDown className={cn("w-3.5 h-3.5 transition-transform", open && "rotate-180")} />
        </button>
      </div>

      {open && (
        <ul
          ref={listRef}
          className="absolute z-50 mt-1 w-full max-h-56 overflow-y-auto rounded border border-slate-200 bg-white shadow-lg"
        >
          {filtered.length === 0 ? (
            <li className="px-3 py-2 text-xs text-slate-400">
              No match for &ldquo;{query}&rdquo;
              <button
                type="button"
                onClick={() => { onChange(query); setOpen(false); setQuery(""); }}
                className="ml-2 text-slate-600 hover:text-slate-800 underline"
              >
                use it anyway
              </button>
            </li>
          ) : (
            filtered.map((o, i) => (
              <li
                key={o.id}
                onClick={() => select(o.id)}
                onMouseEnter={() => setHighlighted(i)}
                className={cn(
                  "px-3 py-2 text-sm cursor-pointer transition-colors",
                  i === highlighted
                    ? "bg-slate-100 text-slate-900"
                    : o.id === value
                    ? "bg-slate-50 font-semibold text-slate-800"
                    : "text-slate-600 hover:bg-slate-50"
                )}
              >
                {o.label}
              </li>
            ))
          )}
          <li className="border-t border-slate-100 px-3 py-1.5 text-[11px] text-slate-400">
            {query
              ? `${filtered.length} of ${options.length}`
              : `${options.length} models`}
          </li>
        </ul>
      )}
    </div>
  );
}
