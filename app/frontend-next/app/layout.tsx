import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { AppShell } from "@/components/layout/AppShell";
import { AppErrorBoundary } from "@/components/layout/AppErrorBoundary";

export const dynamic = "force-dynamic";

const metadataBase = new URL(
  process.env.SITE_URL ??
    process.env.NEXT_PUBLIC_SITE_URL ??
    "http://localhost:3000"
);

export const metadata: Metadata = {
  metadataBase,
  applicationName: "Nexora Tickety",
  title: {
    default: "Tickety by Nexora — Intelligent Service Operations",
    template: "%s · Nexora Tickety",
  },
  description:
    "AI-assisted service operations for decisive triage, accountable ownership, and faster resolution.",
  manifest: "/manifest.webmanifest",
  icons: {
    icon: [
      { url: "/icon.svg", type: "image/svg+xml" },
      { url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
    ],
    shortcut: "/favicon.ico",
    apple: [{ url: "/apple-icon.png", sizes: "180x180", type: "image/png" }],
  },
  openGraph: {
    type: "website",
    siteName: "Nexora Tickety",
    title: "Tickety by Nexora — Intelligent Service Operations",
    description:
      "Resolve what matters with clear triage, accountable ownership, and auditable service operations.",
    images: [
      {
        url: "/opengraph-image.png",
        width: 1200,
        height: 630,
        alt: "Nexora Tickety — Resolve what matters.",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "Tickety by Nexora — Intelligent Service Operations",
    description:
      "Resolve what matters with clear triage, accountable ownership, and auditable service operations.",
    images: ["/twitter-image.png"],
  },
};

export const viewport: Viewport = {
  colorScheme: "light",
  themeColor: "#010D1B",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="nexora-ui">
        <AppErrorBoundary>
          <Providers>
            <AppShell>{children}</AppShell>
          </Providers>
        </AppErrorBoundary>
      </body>
    </html>
  );
}
