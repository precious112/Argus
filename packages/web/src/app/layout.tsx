import type { Metadata } from "next";
import "./globals.css";
import { Sidebar } from "@/components/layout/Sidebar";
import { Providers } from "@/components/providers/Providers";

export const metadata: Metadata = {
  title: "Argus - AI-Native Observability",
  description: "AI-native observability, monitoring, and security platform",
  icons: {
    icon: [
      { url: "/favicon.png", sizes: "256x256", type: "image/png" },
      { url: "/favicon.png", sizes: "48x48", type: "image/png" },
    ],
    apple: { url: "/favicon.png", sizes: "256x256", type: "image/png" },
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="antialiased">
        <Providers>
          <div className="flex h-screen flex-row">
            <Sidebar />
            <main className="flex-1 overflow-y-auto">{children}</main>
          </div>
        </Providers>
      </body>
    </html>
  );
}
