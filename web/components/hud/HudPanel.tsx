import { Eyebrow } from "./Eyebrow";

type Tone = "default" | "emerald" | "gold" | "red";

const TONE_BORDER: Record<Tone, string> = {
  default: "border-hud-neutral", // white-led: neutral edge unless a tone is asked for
  emerald: "border-hud",
  gold: "border-gold/30",
  red: "border-danger/40",
};
const TONE_HOVER: Record<Tone, string> = {
  default: "",
  emerald: "ax-card",
  gold: "ax-card ax-card-gold",
  red: "ax-card ax-card-red",
};

/**
 * HudPanel — the framed neon panel. The workhorse container: near-black
 * surface, hairline emerald border, corner bracket ticks, and an optional
 * title bar (mono eyebrow + optional live dot + right-slot actions).
 *
 * - `title` + `eyebrow` render the header bar. `right` fills the header's
 *   right slot (counts, controls). Omit all three for a bare framed panel.
 * - `tone` tints the border + chooses the hover glow (set `hover` to enable
 *   the lift-on-hover for interactive cards; default panels stay static).
 * - `brackets` draws the corner HUD ticks (default true).
 * - `padded` adds inner body padding (default true); set false when the body
 *   manages its own scroll regions.
 */
export function HudPanel({
  children,
  title,
  eyebrow,
  live = false,
  right,
  tone = "default",
  hover = false,
  brackets = true,
  padded = true,
  className = "",
  bodyClassName = "",
}: {
  children: React.ReactNode;
  /** Title-bar heading (Orbitron). */
  title?: React.ReactNode;
  /** Mono eyebrow above/beside the title. */
  eyebrow?: React.ReactNode;
  /** Pulsing live dot in the eyebrow. */
  live?: boolean;
  /** Right-aligned header slot (counts, buttons). */
  right?: React.ReactNode;
  tone?: Tone;
  /** Enable the lift + glow on hover (for clickable cards). */
  hover?: boolean;
  brackets?: boolean;
  padded?: boolean;
  className?: string;
  bodyClassName?: string;
}) {
  const hasHeader = title != null || eyebrow != null || right != null;
  return (
    <section
      className={`relative overflow-hidden rounded-lg border bg-surface ${
        TONE_BORDER[tone]
      } ${hover ? TONE_HOVER[tone] || "ax-card" : ""} ${
        brackets ? "ax-brackets" : ""
      } ${className}`}
    >
      {hasHeader && (
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-hud-neutral px-5 py-3.5">
          <div className="flex flex-col gap-1">
            {eyebrow != null && (
              <Eyebrow
                live={live}
                // default panels read neutral; the live dot still pulses
                // emerald (handled inside Eyebrow), but the label stays muted
                // unless an explicit tone is requested.
                tone={tone === "default" ? "muted" : (tone as "emerald")}
              >
                {eyebrow}
              </Eyebrow>
            )}
            {title != null && (
              <h2 className="font-display text-[14px] font-bold uppercase tracking-[0.06em] text-fg">
                {title}
              </h2>
            )}
          </div>
          {right != null && <div className="flex items-center gap-2">{right}</div>}
        </header>
      )}
      <div className={`${padded ? "p-5" : ""} ${bodyClassName}`}>{children}</div>
    </section>
  );
}
