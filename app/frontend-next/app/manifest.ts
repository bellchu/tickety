import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Tickety — Intelligent Service Operations",
    short_name: "Tickety",
    description:
      "AI-assisted service operations for decisive triage, accountable ownership, and faster resolution.",
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: "#F6F6F2",
    theme_color: "#0A0B0D",
    icons: [
      {
        src: "/icons/icon-192.png",
        sizes: "192x192",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/icons/icon-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/icons/icon-maskable-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
  };
}
