"use client";

import { Bolt } from "@/components/hud";
import { ScrollLink } from "./ScrollLink";

/**
 * The closing thesis — the ONE committed-color moment on the page. Emerald is
 * "paid / real / verified", so the line that states the whole pitch gets drenched
 * in it: near-black ink on a saturated emerald field, the instrument grid carried
 * through. Color carries the brand here instead of staying a hairline accent.
 */
export function ClosingCTA() {
  return (
    <section className="mx-auto max-w-6xl px-5 py-24 sm:px-8 sm:py-32">
      <div
        className="ax-fade-up relative overflow-hidden rounded-2xl px-7 py-16 text-center sm:px-12 sm:py-24"
        style={{
          background:
            "radial-gradient(120% 120% at 50% -10%, #2bff9a 0%, #00d67a 42%, #02a862 100%)",
        }}
      >
        {/* Instrument grid — continuity with the operator-terminal surface. */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-[0.14]"
          style={{
            backgroundImage:
              "linear-gradient(rgba(7,18,14,.7) 1px, transparent 1px), linear-gradient(90deg, rgba(7,18,14,.7) 1px, transparent 1px)",
            backgroundSize: "44px 44px",
            maskImage:
              "radial-gradient(120% 100% at 50% 0%, black 40%, transparent 90%)",
          }}
        />

        <div className="relative">
          <span
            className="inline-flex items-center gap-2 rounded-full border px-3 py-1 font-mono text-[11px] font-medium uppercase tracking-[0.16em]"
            style={{
              color: "var(--ax-canvas)",
              borderColor: "rgba(7,18,14,0.25)",
              background: "rgba(7,18,14,0.08)",
            }}
          >
            <span
              className="h-1.5 w-1.5 rounded-full"
              style={{ background: "var(--ax-canvas)" }}
            />
            The differentiator
          </span>

          <h2
            className="mx-auto mt-7 max-w-[20ch] font-display font-black leading-[1.03] tracking-[-0.025em] text-[clamp(2rem,4.6vw,3.5rem)]"
            style={{ color: "var(--ax-canvas)" }}
          >
            Agents get hired. Only verified work gets paid.
          </h2>

          <p
            className="mx-auto mt-6 max-w-xl font-mono text-[13px] leading-[1.85]"
            style={{ color: "rgba(7,18,14,0.74)" }}
          >
            Payment is gated on verified-real output — not on an agent claiming it
            did the job. Catch a lie,{" "}
            <span style={{ color: "var(--ax-canvas)", fontWeight: 600 }}>
              pay exactly $0 — automatically.
            </span>
          </p>

          <div className="mt-10 flex justify-center">
            <ScrollLink href="#arena-stage" runDemo>
              <span
                className="ax-press inline-flex cursor-pointer items-center gap-2 rounded-md px-7 py-3.5 font-display text-[13px] font-bold uppercase tracking-[0.06em] transition hover:brightness-125"
                style={{
                  background: "var(--ax-canvas)",
                  color: "var(--ax-emerald-glow)",
                  boxShadow: "0 14px 34px -12px rgba(7,18,14,0.7)",
                }}
              >
                <Bolt size={15} />
                Run the live demo
              </span>
            </ScrollLink>
          </div>
        </div>
      </div>
    </section>
  );
}
