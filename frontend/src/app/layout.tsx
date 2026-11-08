import type { Metadata, Viewport } from "next";
import "./globals.css";
import Providers from "./providers";

export const metadata: Metadata = {
  title: "GridWise: Texas grid forecast",
  description:
    "48-hour forecast of ERCOT grid strain and price-spike risk, with plain-language advice on when to use energy.",
};

export const viewport: Viewport = {
  themeColor: "#0a0b0d",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="dark">
      <body className="antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
