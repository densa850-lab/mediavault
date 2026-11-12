import type { Metadata, Viewport } from "next";
import Link from "next/link";

import { Logo } from "@/components/Logo";

import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "MediaVault",
  description: "Manage, preview and convert your own photos, videos and audio.",
};

export const viewport: Viewport = {
  themeColor: "#0B1F3A",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col">
        <header className="bg-navy text-white">
          <nav
            aria-label="Main"
            className="mx-auto flex max-w-5xl flex-wrap items-center gap-6 px-4 py-3"
          >
            <Link href="/" className="flex items-center gap-2 text-lg font-semibold">
              <Logo />
              MediaVault
            </Link>
            <Link href="/" aria-current="page" className="text-sm text-blue-200 hover:text-white">
              Home
            </Link>
          </nav>
        </header>
        <Providers>
          <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8">{children}</main>
        </Providers>
        <footer className="border-t border-slate-200 py-4 text-center text-xs text-slate-500 dark:border-slate-800">
          MediaVault works only with media you own or are authorized to use.
        </footer>
      </body>
    </html>
  );
}
