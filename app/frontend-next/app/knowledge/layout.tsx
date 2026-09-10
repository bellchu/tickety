import type { Metadata } from "next";

export const metadata: Metadata = { title: "Knowledge base" };

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
