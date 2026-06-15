import type { Config } from "tailwindcss";

/**
 * NEON ARCADE HUD — Tailwind tokens.
 * Mirrors the CSS custom properties in app/globals.css so the palette is
 * usable utility-side: bg-canvas, text-emerald-glow, border-hud, font-display,
 * the radii + glow shadows.
 *
 * THEMING: the semantic NEUTRAL tokens (canvas/surface/fg/borders) and the
 * accent INK tokens (the legible-on-background TEXT shade of each accent) read
 * SPACE-SEPARATED RGB CHANNEL vars via `rgb(var(--ax-x) / <alpha-value>)`, so
 * opacity modifiers (`bg-surface/60`, `text-emerald/40`) STILL work AND the
 * `.ax-light` scope can override the channels to flip the surface light.
 *   - `emerald.DEFAULT` → the INK channel: bright neon on dark, deeper ink on
 *     light. This drives BOTH `text-emerald` (legible both themes) and
 *     `bg-emerald` (a bright CTA fill on dark, a deep readable fill on white).
 *   - `emerald.glow` / `.dim` keep their fixed vivid hue (same hue every theme)
 *     so dots, glows, and low-alpha chips stay neon. `.dim` is overridable.
 */
const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // Canvas + lifted panel surfaces (theme-able channels)
        canvas: "rgb(var(--ax-canvas-rgb) / <alpha-value>)",
        surface: "rgb(var(--ax-surface-rgb) / <alpha-value>)",
        "surface-2": "rgb(var(--ax-surface-2-rgb) / <alpha-value>)",

        // ACCENT 1 — emerald (paid / real / alive / signature).
        // DEFAULT = INK channel (theme-able); glow/dim = fixed neon.
        emerald: {
          DEFAULT: "rgb(var(--ax-emerald-ink) / <alpha-value>)",
          glow: "rgb(var(--ax-emerald-glow-ink) / <alpha-value>)",
          dim: "var(--ax-emerald-dim)",
        },

        // ACCENT 2 — gold (bounty / coins / highlights)
        gold: {
          DEFAULT: "rgb(var(--ax-gold-ink) / <alpha-value>)",
          light: "rgb(var(--ax-gold-light-ink) / <alpha-value>)",
          dim: "var(--ax-gold-dim)",
        },

        // Alert red (FAKE / withheld)
        danger: {
          DEFAULT: "rgb(var(--ax-red-ink) / <alpha-value>)",
          dim: "var(--ax-red-dim)",
        },

        // Text (theme-able channels)
        fg: {
          DEFAULT: "rgb(var(--ax-fg-rgb) / <alpha-value>)",
          muted: "rgb(var(--ax-fg-muted-rgb) / <alpha-value>)",
          faint: "rgb(var(--ax-fg-faint-rgb) / <alpha-value>)",
        },
      },
      borderColor: {
        hud: "rgb(var(--ax-border-rgb) / 0.18)",
        "hud-neutral": "rgb(var(--ax-border-neutral-rgb) / 0.06)",
      },
      fontFamily: {
        display: ["var(--font-display)", "ui-sans-serif", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      borderRadius: {
        sm: "4px",
        md: "8px",
        lg: "12px",
      },
      // Glow shadows reference the CSS vars so `.ax-light` can neutralize them
      // into soft neutral card shadows (neon glows read badly on white).
      boxShadow: {
        "glow-emerald": "var(--ax-glow-emerald)",
        "glow-gold": "var(--ax-glow-gold)",
        "glow-red": "var(--ax-glow-red)",
      },
      transitionTimingFunction: {
        "ax-out": "cubic-bezier(0.16, 1, 0.3, 1)",
        "ax-out-2": "cubic-bezier(0.23, 1, 0.32, 1)",
      },
      // Semantic z-index token scale — mirrors --ax-z-* CSS vars in globals.css.
      // Additive: no existing component z-literals are migrated.
      zIndex: {
        edge: "var(--ax-z-edge)",
        node: "var(--ax-z-node)",
        core: "var(--ax-z-core)",
        "node-hover": "var(--ax-z-node-hover)",
        drawer: "var(--ax-z-drawer)",
        toast: "var(--ax-z-toast)",
      },
    },
  },
  plugins: [],
};

export default config;
