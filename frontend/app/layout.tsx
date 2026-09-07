import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "DealFlow Agents",
  description: "Sales pipeline, AI agents, and a deterministic rules engine",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
