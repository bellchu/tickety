import type { MetadataRoute } from "next";
import { PRODUCT_MARKETING_TITLE, PRODUCT_NAME } from "@/lib/brand";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: PRODUCT_MARKETING_TITLE,
    short_name: PRODUCT_NAME,
    description:
      "AI-assisted service operations for decisive triage, accountable ownership, and faster resolution.",
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: "#F8FAFE",
    theme_color: "#010D1B",
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
