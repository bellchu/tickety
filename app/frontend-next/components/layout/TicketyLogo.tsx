export function TicketyLogo({ className = "h-6" }: { className?: string }) {
  return (
    <div className={`flex items-center gap-2.5 ${className}`}>
      <div
        className="flex h-9 w-9 items-center justify-center rounded-[10px]"
        style={{
          background: "linear-gradient(135deg, #C77B4F 0%, #9A5A36 100%)",
          boxShadow: "0 2px 4px rgba(154, 90, 54, 0.25), inset 0 1px 0 rgba(255,255,255,0.15)",
        }}
      >
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <path
            d="M2.5 0C1.12 0 0 1.12 0 2.5V4C0.83 4 1.5 4.67 1.5 5.5C1.5 6.33 0.83 7 0 7V11.5C0 12.88 1.12 14 2.5 14H15.5C16.88 14 18 12.88 18 11.5V7C17.17 7 16.5 6.33 16.5 5.5C16.5 4.67 17.17 4 18 4V2.5C18 1.12 16.88 0 15.5 0H2.5Z"
            transform="translate(1, 3)"
            fill="#FBF8F3"
            fillOpacity="0.95"
          />
          <path
            d="M4 8C3.87 8 3.74 7.95 3.64 7.85L0.4 4.6C0.2 4.4 0.2 4.09 0.4 3.89C0.6 3.69 0.91 3.69 1.11 3.89L4 6.79L9.64 1.15C9.84 0.95 10.15 0.95 10.35 1.15C10.55 1.35 10.55 1.66 10.35 1.86L4.36 7.85C4.26 7.95 4.13 8 4 8Z"
            transform="translate(4, 5)"
            fill="#9A5A36"
          />
        </svg>
      </div>
      <div className="flex flex-col leading-none gap-0.5">
        <span className="font-serif text-base font-semibold italic text-ink-700">
          Tickety
        </span>
        <span className="text-[10px] text-ink-400">Support Suite</span>
      </div>
    </div>
  );
}