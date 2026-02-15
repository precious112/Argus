import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Argus - AI-Native Observability",
  description: "AI-native observability, monitoring, and security platform",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="antialiased">
        <div className="flex h-screen flex-col">
          <header className="flex items-center justify-between border-b border-[var(--border)] px-4 py-2">
            <div className="flex items-center gap-3">
              <h1 className="text-lg font-semibold tracking-tight">Argus</h1>
              <span className="rounded bg-argus-600/20 px-2 py-0.5 text-xs text-argus-400">
                v0.1.0
              </span>
            </div>
            <nav className="flex items-center gap-4 text-sm text-[var(--muted)]">
              <a href="/" className="hover:text-[var(--foreground)]">
                Chat
              </a>
              <a href="/services" className="hover:text-[var(--foreground)]">
                Services
              </a>
              <a href="/history" className="hover:text-[var(--foreground)]">
                History
              </a>
              <a href="/settings" className="hover:text-[var(--foreground)]">
                Settings
              </a>
            </nav>
          </header>
          <main className="flex-1 overflow-hidden">{children}</main>
        </div>
      </body>
    </html>
  );
}
