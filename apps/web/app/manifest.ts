import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "AI Neta — Aapki baat, aapka haq",
    short_name: "AI Neta",
    description: "Public-safe civic complaint tracking and help.",
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: "#FFFDF7",
    theme_color: "#0B6E4F",
    lang: "hi",
    icons: [
      {
        src: "/icon-192.png",
        sizes: "192x192",
        type: "image/png",
        purpose: "maskable",
      },
      {
        src: "/icon-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
  };
}
