"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { Search, ChevronDown } from "lucide-react";
import { filterModelOptions, type ModelOption } from "@/lib/model-options";
import { cn } from "@/lib/utils";

interface Props {
  value: string;
  options: ModelOption[];
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
  const triggerRef = useRef<HTMLButtonElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const listboxId = useId();

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
        setQuery("");
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const filtered = filterModelOptions(options, query);
  const customModelId = query.trim();

  const selectedOption = options.find((o) => o.id === value);

  const select = (id: string) => {
    onChange(id);
    setOpen(false);
    setQuery("");
    requestAnimationFrame(() => triggerRef.current?.focus());
  };

  const openMenu = () => {
    const selectedIndex = options.findIndex((option) => option.id === value);
    setQuery("");
    setHighlighted(selectedIndex >= 0 ? selectedIndex : 0);
    setOpen(true);
  };

  const closeMenu = (restoreFocus = false) => {
    setOpen(false);
    setQuery("");
    if (restoreFocus) {
      requestAnimationFrame(() => triggerRef.current?.focus());
    }
  };

  const handleSearchKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlighted((current) =>
        filtered.length > 0 ? Math.min(current + 1, filtered.length - 1) : 0,
      );
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlighted((current) => Math.max(current - 1, 0));
    } else if (e.key === "Enter" && filtered[highlighted]) {
      e.preventDefault();
      select(filtered[highlighted].id);
    } else if (e.key === "Enter" && customModelId) {
      e.preventDefault();
      select(customModelId);
    } else if (e.key === "Escape") {
      e.preventDefault();
      closeMenu(true);
    }
  };

  useEffect(() => {
    if (!open) return;
    const frame = requestAnimationFrame(() => searchRef.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, [open]);

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
      <button
        ref={triggerRef}
        type="button"
        aria-label="Choose model"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listboxId : undefined}
        onClick={() => (open ? closeMenu() : openMenu())}
        onKeyDown={(event) => {
          if (!open && (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ")) {
            event.preventDefault();
            openMenu();
          }
        }}
        className="input-base flex items-center justify-between gap-2 text-left disabled:cursor-not-allowed disabled:opacity-60"
        disabled={disabled}
      >
        <span className={cn("truncate", !value && "text-ink-400")}>
          {selectedOption?.label || value || placeholder}
        </span>
        <ChevronDown
          aria-hidden="true"
          className={cn("h-3.5 w-3.5 shrink-0 text-ink-400 transition-transform", open && "rotate-180")}
        />
      </button>

      {open && (
        <div className="absolute z-50 mt-1 w-full overflow-hidden rounded border border-linen-400 bg-linen-50 shadow-lg">
          <div className="border-b border-linen-300 p-2">
            <div className="relative">
              <Search
                aria-hidden="true"
                className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-400"
              />
              <input
                ref={searchRef}
                type="search"
                role="combobox"
                aria-label="Search models"
                aria-autocomplete="list"
                aria-expanded="true"
                aria-controls={listboxId}
                aria-activedescendant={
                  filtered[highlighted]
                    ? `${listboxId}-option-${highlighted}`
                    : undefined
                }
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setHighlighted(0);
                }}
                onKeyDown={handleSearchKeyDown}
                placeholder="Search models…"
                className="input-base input-search"
              />
            </div>
          </div>

          <ul
            ref={listRef}
            id={listboxId}
            role="listbox"
            aria-label="Models"
            className="max-h-56 overflow-y-auto"
          >
            {filtered.map((option, index) => (
              <li
                id={`${listboxId}-option-${index}`}
                key={option.id}
                role="option"
                aria-selected={option.id === value}
                onClick={() => select(option.id)}
                onMouseEnter={() => setHighlighted(index)}
                className={cn(
                  "cursor-pointer px-3 py-2 text-sm transition-colors",
                  index === highlighted
                    ? "bg-linen-300 text-ink-700"
                    : option.id === value
                      ? "bg-linen-200 font-semibold text-ink-700"
                      : "text-ink-600 hover:bg-linen-200",
                )}
              >
                <span className="block truncate">{option.label}</span>
                {option.id !== option.label && (
                  <span className="block truncate text-[11px] font-normal text-ink-400">
                    {option.id}
                  </span>
                )}
              </li>
            ))}
          </ul>

          {filtered.length === 0 && (
            <div className="px-3 py-2 text-xs text-ink-400">
              No match for &ldquo;{query}&rdquo;
              {customModelId && (
                <button
                  type="button"
                  onClick={() => select(customModelId)}
                  className="ml-2 text-ink-600 underline hover:text-ink-700"
                >
                  use it anyway
                </button>
              )}
            </div>
          )}

          <div className="border-t border-linen-300 px-3 py-1.5 text-[11px] text-ink-400">
            {query
              ? `${filtered.length} of ${options.length}`
              : `${options.length} models`}
          </div>
        </div>
      )}
    </div>
  );
}
