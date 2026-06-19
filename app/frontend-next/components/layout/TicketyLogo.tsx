export function TicketyLogo({ className = "h-6" }: { className?: string }) {
  return (
    <div className={`flex items-center gap-2.5 ${className}`}>
      {/* Ticket icon — clean geometric */}
      <svg
        width="20"
        height="20"
        viewBox="0 0 20 20"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        aria-hidden="true"
      >
        <rect
          x="1"
          y="2"
          width="18"
          height="16"
          rx="3"
          className="fill-slate-800"
        />
        <line
          x1="9"
          y1="4"
          x2="9"
          y2="16"
          stroke="white"
          strokeWidth="1.2"
          strokeDasharray="1.2 1.6"
        />
        <path
          d="M5 10l2.5 2.5 5-5"
          stroke="white"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
          fill="none"
        />
      </svg>
      <span className="text-base font-bold tracking-tight text-slate-900">
        Tickety
      </span>
    </div>
  );
}
