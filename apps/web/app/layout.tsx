import type { Metadata } from "next";
import ServiceWorkerRegister from "../components/service-worker-register";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Neta — Aapki baat, aapka haq",
  description: "Track a civic complaint with its private receipt token.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="hi">
      <body><ServiceWorkerRegister />{children}</body>
    </html>
  );
}
