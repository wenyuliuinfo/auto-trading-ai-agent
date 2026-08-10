import type { Metadata } from "next";
import { LayoutGrid, ShieldCheck } from "lucide-react";

import "./globals.css";

export const metadata: Metadata = {
  title: "Auto Trading AI Agent",
  description: "Theme-driven stock and ETF basket research workspace",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <div className="ambient" aria-hidden="true">
          <div className="ambient-base" />
          <div className="ambient-grid" />
          <div className="ambient-noise" />
          <div className="blob blob-a" />
          <div className="blob blob-b" />
          <div className="blob blob-c" />
        </div>
        <header className="nav">
          <div className="nav-inner">
            <div className="brand-mark">
              <LayoutGrid size={18} aria-hidden />
            </div>
            <div className="brand-name">Auto Trading AI Agent</div>
            <div className="nav-meta">
              <span className="compliance-pill">
                <ShieldCheck size={12} aria-hidden />
                Research only
              </span>
            </div>
          </div>
        </header>
        <main className="page">
          {children}
        </main>
      </body>
    </html>
  );
}
