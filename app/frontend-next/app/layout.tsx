import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { Sidebar } from "@/components/layout/Sidebar";
import { Footer } from "@/components/layout/Footer";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Tickety — Intelligent Support Operations",
  description: "AI-powered ticket triage with performance engagement",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <Providers>
          <div className="flex min-h-screen">
            <Sidebar />
            <div className="flex flex-1 flex-col pl-56">
              <main className="flex-1">
                <div className="mx-auto max-w-7xl px-8 py-8">
                  {children}
                </div>
              </main>
              <Footer />
            </div>
          </div>
        </Providers>
      </body>
    </html>
  );
}
