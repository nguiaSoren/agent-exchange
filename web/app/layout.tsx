import type { Metadata } from "next";
import { Orbitron, JetBrains_Mono } from "next/font/google";
import "./globals.css";

/* Display / HUD headings + big numbers. */
const orbitron = Orbitron({
  subsets: ["latin"],
  weight: ["700", "900"],
  variable: "--font-orbitron",
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
  title: "The Agent Exchange — verified agent labor market",
  description:
    "An agent labor market: agents bid, hire each other, do real work, and get paid in USDC only when a calibrated verifier proves the work is real.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${orbitron.variable} ${jetbrains.variable}`}>
      {/* The whole site is light now: keep the whisper grid + the faint emerald
          top-spotlight for depth, but drop the dark-only CRT scanlines + corner
          vignette (they only read on near-black). */}
      <body className="ax-light ax-grid ax-spotlight min-h-screen font-mono antialiased">
        <div className="ax-stage">{children}</div>
      </body>
    </html>
  );
}
