import type { ReactNode } from "react";

const ICONS: Record<string, ReactNode> = {
  grid: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7v5l3 2" />
    </>
  ),
  sliders: (
    <>
      <path d="M4 7h5m4 0h7M4 17h9m4 0h3" />
      <circle cx="11" cy="7" r="2" />
      <circle cx="15" cy="17" r="2" />
    </>
  ),
  book: <path d="M12 5v15M3 4c4-1 6 0 9 2 3-2 5-3 9-2v15c-4-1-6 0-9 2-3-2-5-3-9-2z" />,
  layers: (
    <>
      <path d="m12 3 9 5-9 5-9-5 9-5Zm-8 9 8 4 8-4M4 16l8 4 8-4" />
    </>
  ),
  settings: (
    <>
      <path d="m9 3-.5 2.4-2 1.2-2.3-.7L2.5 9l1.8 1.7v2.6L2.5 15l1.7 3.1 2.3-.7 2 1.2L9 21h6l.5-2.4 2-1.2 2.3.7 1.7-3.1-1.8-1.7v-2.6L21.5 9l-1.7-3.1-2.3.7-2-1.2L15 3z" />
      <circle cx="12" cy="12" r="3" />
    </>
  ),
  help: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M9.3 9a2.8 2.8 0 0 1 5.5.6c0 1.8-2.8 2-2.8 4M12 17h.01" />
    </>
  ),
  search: (
    <>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="m16 16 4.5 4.5" />
    </>
  ),
  bell: <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 8h18c0-1-3-1-3-8M10 20h4" />,
  menu: <path d="M4 6h16M4 12h16M4 18h16" />,
  plus: <path d="M12 5v14M5 12h14" />,
  arrow: <path d="M4 12h15m-5-5 5 5-5 5" />,
  chevron: <path d="m9 5 7 7-7 7" />,
  check: <path d="m5 12 4 4 10-10" />,
  checkCircle: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="m7.5 12 3 3 6-6" />
    </>
  ),
  file: <path d="M14 3H5v18h14V8l-5-5Zm0 0v5h5M8 13h8M8 17h5" />,
  calendar: (
    <>
      <rect x="3" y="5" width="18" height="16" rx="2" />
      <path d="M7 3v4m10-4v4M3 10h18M7 14h3m4 0h3" />
    </>
  ),
  globe: (
    <>
      <circle cx="12" cy="12" r="9" />
      <ellipse cx="12" cy="12" rx="4" ry="9" />
      <path d="M3 12h18" />
    </>
  ),
  chip: (
    <>
      <rect x="6" y="6" width="12" height="12" rx="2" />
      <path d="M9 3v3m6-3v3M9 18v3m6-3v3M3 9h3m-3 6h3m12-6h3m-3 6h3" />
      <rect x="9" y="9" width="6" height="6" rx="1" />
    </>
  ),
  chart: <path d="M4 4v16h17M8 15l4-5 4 2 4-6" />,
  spark: <path d="m12 3 2.2 6.8L21 12l-6.8 2.2L12 21l-2.2-6.8L3 12l6.8-2.2z" />,
  users: (
    <>
      <circle cx="9" cy="8" r="3" />
      <path d="M3 20v-2a6 6 0 0 1 12 0v2M16 5a3 3 0 0 1 0 6m2 3a5 5 0 0 1 3 4v2" />
    </>
  ),
  news: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M7 8h10M7 12h4m3 0h3M7 16h4m3 0h3" />
    </>
  ),
  building: <path d="M5 21V3h14v18M2 21h20M9 7h1m4 0h1M9 11h1m4 0h1M9 15h1m4 0h1M10 21v-3h4v3" />,
  download: <path d="M12 3v12m-4-4 4 4 4-4M4 17v4h16v-4" />,
  close: <path d="m6 6 12 12M6 18 18 6" />,
  sort: <path d="M8 4v16m-4-4 4 4 4-4M16 20V4m-4 4 4-4 4 4" />,
  shield: (
    <>
      <path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z" />
      <path d="m8 12 3 3 5-6" />
    </>
  ),
  warning: <path d="m12 3 10 18H2zM12 9v5m0 3h.01" />,
  pause: <path d="M8 5v14M16 5v14" />,
  play: <path d="m7 4 14 8-14 8z" />,
  refresh: (
    <>
      <path d="M20 7v5h-5M4 17v-5h5" />
      <path d="M5.5 7a7.5 7.5 0 0 1 12.4-2L20 8M4 16l2.1 3A7.5 7.5 0 0 0 18.5 17" />
    </>
  ),
  moon: <path d="M20.5 14.3A9 9 0 0 1 9.7 3.5 9 9 0 1 0 20.5 14.3Z" />,
  activity: <path d="M3 12h4l3-8 4 16 3-8h4" />,
  folder: <path d="M3 7V4h7l3 3h8v13H3z" />,
  wallet: <path d="M20 8V5H4a2 2 0 0 0 0 4h17v11H4V7m12 5h5v5h-5z" />,
  stop: <rect x="5" y="5" width="14" height="14" rx="2" />,
};

export function Icon({ name, className }: { name: string; className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {ICONS[name] ?? ICONS.file}
    </svg>
  );
}
