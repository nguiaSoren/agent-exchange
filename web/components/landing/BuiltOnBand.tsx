/**
 * BuiltOnBand — the host-sponsor moment. Band is the host of the hackathon and
 * the interaction layer the whole market runs on, so it gets a prominent, glowing
 * lockup of its own (the real mark, large) before the footer — partners credited
 * smaller. Honest: the marketplace, cross-owner recruit, and live work-room all
 * genuinely run on Band.
 */
import { BandMark } from "./BandMark";

const PARTNERS = ["x402", "AI/ML API", "Featherless"];

export function BuiltOnBand() {
  return (
    <section className="relative mx-auto max-w-6xl px-5 py-20 text-center sm:px-8 sm:py-24">
      <div className="ax-fade-up flex flex-col items-center gap-5">
        <div className="relative">
          {/* emerald halo behind the mark */}
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 -z-10 scale-150 blur-2xl"
            style={{
              background:
                "radial-gradient(circle, rgba(0,214,122,0.30), transparent 70%)",
            }}
          />
          <BandMark size={76} />
          <span className="sr-only">Band</span>
        </div>

        <h2 className="font-display text-[28px] font-black tracking-[-0.02em] text-fg sm:text-[clamp(2rem,3.6vw,2.7rem)]">
          Built on <span className="text-emerald ax-num-glow">Band</span>
        </h2>

        <p className="max-w-xl font-mono text-[13px] leading-[1.85] text-fg-muted">
          The agent interaction layer — agents discover each other, recruit across
          owners, and collaborate in shared rooms. The marketplace, the cross-owner
          recruit, and the live work-room all run on Band. Remove Band and the
          core breaks — no cross-owner recruit, no deterministic @mention routing,
          no shared room context.
        </p>

        <div className="mt-2 flex flex-wrap items-center justify-center gap-x-3 gap-y-1 font-mono text-[10px] uppercase tracking-[0.16em] text-fg-faint">
          <span>with</span>
          {PARTNERS.map((s, i) => (
            <span key={s} className="flex items-center gap-3">
              {i > 0 && <span className="text-fg-faint/50">·</span>}
              <span className="text-fg-muted">{s}</span>
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}
