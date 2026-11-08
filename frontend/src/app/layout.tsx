import type { Metadata, Viewport } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "./globals.css";
import Providers from "./providers";

export const metadata: Metadata = {
  title: "GridWise: Texas grid forecast",
  description:
    "48-hour forecast of ERCOT grid strain and price-spike risk, with plain-language advice on when to use energy.",
};

export const viewport: Viewport = {
  themeColor: "#07080a",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    // suppressHydrationWarning: browser extensions (Grammarly, password managers, dark-mode
    // tools) inject attributes into <html>/<body> before React loads. This only silences
    // attribute mismatches on these two tags, not on anything inside them.
    <html lang="en" className={`dark ${GeistSans.variable} ${GeistMono.variable}`} suppressHydrationWarning>
      <body className="antialiased" suppressHydrationWarning>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
