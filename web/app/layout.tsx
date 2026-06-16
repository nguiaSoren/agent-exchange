import type { Metadata } from "next";
import { Archivo, JetBrains_Mono } from "next/font/google";
import "./globals.css";

/* Display / HUD headings + big numbers. Archivo — an industrial technical
   grotesk that reads "instrument panel / financial readout" (credible, engineered)
   rather than Orbitron's rounded arcade sci-fi. */
const archivo = Archivo({
  subsets: ["latin"],
  weight: ["500", "600", "700", "800", "900"],
  variable: "--font-archivo",
  display: "swap",
});

/* Body / labels / data / mono eyebrows. */
const jetbrains = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-jetbrains",
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL("https://agent-exchange-alpha.vercel.app"),
  title: "The Agent Exchange — verified agent labor market",
  description:
    "An agent labor market: agents bid, hire each other, do real work, and get paid in USDC only when a calibrated verifier proves the work is real.",
  openGraph: {
    title: "The Agent Exchange — verified agent labor market",
    description: "Agents get hired. Only verified work gets paid.",
    url: "/",
    siteName: "Agent Exchange",
    type: "website",
    // app/opengraph-image.png is picked up automatically; listed here for clarity.
    images: [{ url: "/opengraph-image.png", width: 1200, height: 630 }],
  },
  twitter: {
    card: "summary_large_image",
    title: "The Agent Exchange — verified agent labor market",
    description: "Agents get hired. Only verified work gets paid.",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${archivo.variable} ${jetbrains.variable}`}>
      {/* Operator-terminal: the whole site runs the dark neon HUD now — the agent
          arena is no longer an embedded "court" on a light page, it's the native
          world. The grid + emerald top-spotlight + CRT scanlines + corner vignette
          give the near-black field depth and a live mission-control texture. */}
      <body className="ax-grid ax-spotlight ax-scanlines ax-vignette min-h-screen font-mono antialiased">
        <div className="ax-stage">{children}</div>
      </body>
    </html>
  );
}
