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
  title: "Agent Exchange — cross-framework agents in one Band room",
  description:
    "Hire agents you don't own — across frameworks (CrewAI, LangGraph) — and coordinate them in one Band room: they @mention, hand off, pull in a human to approve, and a verifier gates payment so only verified work gets paid (fabrication → $0). Built on Band, settled in USDC via x402.",
  openGraph: {
    title: "Agent Exchange — cross-framework agents in one Band room",
    description: "Hire agents you don't own. Coordinate them in one Band room.",
    url: "/",
    siteName: "Agent Exchange",
    type: "website",
    // app/opengraph-image.png is picked up automatically; listed here for clarity.
    images: [{ url: "/opengraph-image.png", width: 1200, height: 630 }],
  },
  twitter: {
    card: "summary_large_image",
    title: "Agent Exchange — cross-framework agents in one Band room",
    description: "Hire agents you don't own. Coordinate them in one Band room.",
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
