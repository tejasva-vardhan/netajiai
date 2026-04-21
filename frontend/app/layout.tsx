import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI NETA - शिवपुरी",
  description: "Civic complaint chatbot for Shivpuri",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="hi">
      <body className="antialiased min-h-screen">{children}</body>
    </html>
  );
}
