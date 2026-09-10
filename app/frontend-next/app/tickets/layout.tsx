import type { Metadata } from "next";

export const metadata: Metadata = { title: "All tickets" };

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
