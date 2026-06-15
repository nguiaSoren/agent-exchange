# The Agent Exchange — Neon Arcade HUD design system

The locked foundation (Wave 1). Build every component against this. A cinematic heads-up display that is **white-led on near-black**, with emerald + gold as **sparing** signature accents, scanline/glitch/pulse motion, live and alive. The system is **theme-able**: the same token names render a dark HUD by default and a clean white editorial surface under the `.ax-light` scope (see §1b).

**Wave 2 must NOT edit these files:** `app/globals.css`, `app/layout.tsx`, `tailwind.config.ts`, `components/hud/*`, `lib/events.ts`, `lib/runState.ts`, `lib/stream.ts`, `lib/mockRun.ts`. The SSE event contract and reducer are FROZEN. Restyle the demo components (`Dashboard`, `JobCard`, `StageBar`, `BidFeed`, `WorkRoom`, `SettleBar`, `Avatar`) by consuming the hud primitives + tokens below. `VerifyPanel` is already done — pattern-match it.

---

## 1. Color tokens

The neutral surfaces/text/borders and each accent's **text ink** are theme-able. They are stored as space-separated RGB **channel** vars with a `-rgb` suffix (e.g. `--ax-canvas-rgb: 7 18 14`) and mapped in Tailwind as `rgb(var(--ax-canvas-rgb) / <alpha-value>)` — so **opacity modifiers keep working** (`bg-surface/60`, `text-fg-muted/40`, `text-emerald/30`) AND `.ax-light` can override the channel to re-theme. Each channel also has a resolved **color alias** under the bare name (`--ax-canvas: rgb(var(--ax-canvas-rgb))`) for any inline-`style` consumer; the alias re-derives under `.ax-light` automatically.

The bright **neon accent fills** (`--ax-emerald`, `--ax-emerald-glow`, the `*-dim` chips, `--ax-gold`, `--ax-red`) stay vivid hex — same hue every theme — for dots, glows, and low-alpha chips.

Default values below are the **dark (de-greened, white-led)** theme. `text-emerald`/`text-gold`/`text-danger` resolve to the accent **INK** channel, which darkens to a legible shade under `.ax-light`.

| Token | Dark value | Channel var (themed) | Tailwind utility | Use |
|---|---|---|---|---|
| Canvas base | `#07120E` | `--ax-canvas-rgb` (alias `--ax-canvas`) | `bg-canvas` | page background (set on `<body>` via `.ax-grid`) |
| Surface | `#0B1A14` | `--ax-surface-rgb` (alias `--ax-surface`) | `bg-surface` | a panel on the canvas |
| Surface 2 | `#0E211A` | `--ax-surface-2-rgb` (alias `--ax-surface-2`) | `bg-surface-2` | a raised element inside a panel |
| Emerald (ink) | `#00D67A` | `--ax-emerald-ink` | `bg-emerald` `text-emerald` `border-emerald` | paid / real / alive / primary CTA. **Text ink** — darkens on light |
| Emerald glow (ink) | `#2BFF9A` | `--ax-emerald-glow-ink` | `text-emerald-glow` `bg-emerald-glow` | bright accent / hover. Darkens on light |
| Emerald dim | `rgba(0,214,122,0.18)` | `--ax-emerald-dim` (fixed neon) | `bg-emerald-dim` | dim fills / chips — keeps neon hue |
| Gold (ink) | `#FFC233` | `--ax-gold-ink` | `text-gold` `bg-gold` `border-gold` | bounty / coins / money / PARTIAL. Darkens on light |
| Gold light (ink) | `#FFD56A` | `--ax-gold-light-ink` | `text-gold-light` | gold hover. Darkens on light |
| Gold dim | `rgba(255,194,51,0.18)` | `--ax-gold-dim` (fixed neon) | `bg-gold-dim` | dim gold fills — keeps neon hue |
| Danger (ink) | `#FF3B5C` | `--ax-red-ink` | `text-danger` `bg-danger` `border-danger` | FAKE / withheld / alert. Darkens on light |
| Danger dim | `rgba(255,59,92,0.18)` | `--ax-red-dim` (fixed neon) | `bg-danger-dim` | dim red fills — keeps neon hue |
| Foreground | `#EEF3F1` | `--ax-fg-rgb` (alias `--ax-fg`) | `text-fg` | primary text — **neutral near-white** (de-greened) |
| FG muted | `#9DAAA4` | `--ax-fg-muted-rgb` (alias `--ax-fg-muted`) | `text-fg-muted` | secondary text — **neutral gray** (de-greened) |
| FG faint | `#52685E` | `--ax-fg-faint-rgb` (alias `--ax-fg-faint`) | `text-fg-faint` | faint labels / disabled |
| Border (HUD) | `rgba(0,214,122,0.18)` | `--ax-border-rgb` (alias `--ax-border`) | `border-hud` | emerald-tinted hairline (fixed 0.18 alpha) |
| Border (neutral) | `rgba(255,255,255,0.06)` | `--ax-border-neutral-rgb` (alias `--ax-border-neutral`) | `border-hud-neutral` | neutral panel edge (fixed 0.06 alpha) |

> **De-green note.** The dark theme is now white-led: foreground is a neutral near-white (`#EEF3F1`, not the old green `#E8FBF1`), muted is a neutral gray (`#9DAAA4`, not `#7E9D90`), the body grid line is neutral (`rgba(255,255,255,0.035)`, was emerald), and the HUD primitives default to **neutral** (see §4 — `HudPanel` default border is `border-hud-neutral`, `Eyebrow` default tone is muted). The emerald radial spotlight stays (the signature). Reserve emerald/gold/red for SEMANTIC roles only: emerald = real/paid/live/primary-CTA, gold = money/bounty/coins, red = fake/withheld.

**Verdict semantics:** REAL/pass → emerald · FAKE/withheld → red · PARTIAL → gold/amber. The verdict text classes (`.ax-verdict-*`) use the accent **ink** channel so they stay legible on both themes. Canonical mapping lives in `lib/ui.ts › verdictStyle(v)` → `{ label, glyph, fg, bg, highlight, border }`.

**Glow shadows (Tailwind):** `shadow-glow-emerald`, `shadow-glow-gold`, `shadow-glow-red`. CSS vars: `--ax-glow-emerald`, `--ax-glow-gold`, `--ax-glow-red` — these are **theme vars**: neon glows on dark, soft neutral card shadows under `.ax-light`.

**Radii:** `rounded-sm` = 4px, `rounded-md` = 8px, `rounded-lg` = 12px (also `--ax-r-sm/md/lg`).

**Easing (Tailwind):** `ease-ax-out` = `cubic-bezier(0.16,1,0.3,1)`, `ease-ax-out-2` = `cubic-bezier(0.23,1,0.32,1)`. CSS vars `--ax-ease-out`, `--ax-ease-out-2`.

---

## 1b. `.ax-light` — the white / bone theme scope

The light theme is a **scope class**, not a global mode. Wrap any section you want light:

```tsx
<div className="ax-light bg-canvas">
  {/* every hud primitive + token inside now renders the light surface */}
</div>
```

`.ax-light` overrides only the theme-able **channels** (neutrals + accent ink), the grid/ambience tints, the glow shadows, and the dim-chip alphas. The same token names (`bg-canvas`, `bg-surface`, `text-fg`, `text-emerald`, `border-hud`, `shadow-glow-emerald`, …) and the same primitives (`HudPanel`, `Eyebrow`, `NeonButton`, …) resolve to a clean white editorial card surface — no component changes required.

**Light values:**

| Token | Light value | Notes |
|---|---|---|
| `bg-canvas` | `#FBFBF9` | warm bone page base |
| `bg-surface` | `#FFFFFF` | a card on the bone |
| `bg-surface-2` | `#F1F3EF` | a raised element in a card |
| `text-fg` | `#0E1A14` | near-black ink |
| `text-fg-muted` | `#5C6B63` | mid gray |
| `text-fg-faint` | `#8B978F` | light gray |
| `border-hud` | `#067A4A` @ 0.18 | faint emerald-tint hairline |
| `border-hud-neutral` | `#0E1A14` @ 0.06 | light neutral edge |
| `text-emerald` (ink) | `#067A4A` | deeper emerald, ~4.5:1 on white |
| `text-emerald-glow` (ink) | `#05663E` | deeper still |
| `text-gold` (ink) | `#9A6B00` | deeper gold, legible on white |
| `text-danger` (ink) | `#C72A41` | deeper red, legible on white |

**Accent-ink mechanism.** `text-emerald` / `text-gold` / `text-danger` map to the accent **ink channel** (`--ax-emerald-ink`, `--ax-gold-ink`, `--ax-red-ink`). On dark these channels are the bright neon; `.ax-light` overrides them to deeper, ~4.5:1-legible inks. So accent **text** auto-darkens on white. Because `bg-emerald` shares the ink DEFAULT, the **primary CTA fill also deepens** on white (a deep-emerald button with bone text, not a washed-out neon fill). Accent **fills / chips** that should stay bright at low alpha (`bg-emerald-dim`, dots, glows) use the separate fixed-neon vars and keep their hue (the dim chips just bump alpha slightly under `.ax-light` so they register on white).

**Softened shadows.** Under `.ax-light`, `--ax-glow-emerald/gold/red` and `--ax-shadow-card` become soft, low-opacity **neutral** shadows (`0 1px 3px rgba(14,26,20,0.06), 0 8px 24px -12px rgba(14,26,20,0.12)`) so panels read as clean cards, not neon. The grid line, spotlight, vignette, and scanline all drop to faint neutral so the canvas isn't veiled.

**How to make a section light (for the landing agent).** Wrap the landing in `<div className="ax-light bg-canvas">…</div>` (or apply `ax-light` to any sub-section). Then build with the **exact same** tokens and hud primitives as the dark UI — `HudPanel`, `Eyebrow`, `NeonButton`, `bg-surface`, `text-fg`, `text-fg-muted`, `text-emerald`, `shadow-glow-emerald`, etc. Do **not** hard-code light hexes; the scope handles it. Use `text-emerald`/`text-gold` for accent text (they auto-darken), `bg-emerald` for the primary CTA (deepens to a readable fill), and `bg-emerald-dim`/`bg-gold-dim` for chips. The dark `.ax-grid`/`.ax-spotlight`/`.ax-scanlines`/`.ax-vignette` body layers are still on `<body>` from `layout.tsx` but go faint-neutral inside the scope; if the landing wants a pure-white field, give the wrapper its own `bg-canvas` (as shown) so it paints over the body grid.

---

## 2. Typography

| Role | Font | Weights | CSS variable | Tailwind |
|---|---|---|---|---|
| Display / HUD headings + big numbers | **Orbitron** | 700, 900 | `--font-display` (← `--font-orbitron`) | `font-display` |
| Body / labels / data / mono eyebrows | **JetBrains Mono** | 400, 500 | `--font-mono` (← `--font-jetbrains`) | `font-mono` |

Both wired in `app/layout.tsx` via `next/font/google`; the variables are set on `<html>`. `<body>` defaults to `font-mono`. Use `font-display` explicitly for headings, big numbers, verdict labels. Use `.tnum` for tabular numerals on money / metrics / hashes.

---

## 3. `ax-` utilities & keyframes (in `app/globals.css`)

**Background layers** (composed on `<body>` in layout; content sits in `.ax-stage`):
- `.ax-grid` — static **neutral** grid on the canvas (de-greened; line tint `--ax-grid-line`, faint neutral on both themes).
- `.ax-spotlight` — fixed radial **emerald** spotlight at top (the signature; whisper of emerald under `.ax-light`).
- `.ax-scanlines` — fixed faint CRT horizontal scanline texture.
- `.ax-vignette` — fixed corner darkening.
- `.ax-stage` — `position:relative; z-index:1` wrapper so content sits above the fixed bg layers.

**Scroll:** `.ax-scroll` (thin emerald scrollbar; webkit styles are global too).

**Entrance / stagger:**
- `.ax-fade-up` — one-shot fade + rise (360ms).
- `.ax-stagger` — list entrance; set `--index` (0,1,2…) per child → 45ms stagger.

**Press / hover:**
- `.ax-press` — transition wrapper; `scale(0.97)` on `:active`.
- `.ax-card` — lift + emerald glow border on hover. Variants: `.ax-card-gold`, `.ax-card-red` (compose with `.ax-card`; `.ax-card-red` also tints the resting border).

**Motion accents:**
- `.ax-pulse` — compositor-only opacity pulse (infinite). `.ax-breathe` — quicker variant for active dots.
- `.ax-glitch` — chromatic glitch on `:hover`. `.ax-glitch-live` — continuous glitch (reserve for the FAKE moment).
- `.ax-scanline` — a bright bar sweeps across the element (put on `position:relative` containers).
- `.ax-caret::after` / `.ax-caret-blink` — blinking terminal caret.
- `.ax-marquee` (+ `.ax-marquee-pause` parent to pause on hover) — horizontal loop; duplicate content 2× for seamless.
- `.ax-brackets` — corner HUD tick brackets (applied automatically by `HudPanel`).

**Bars / counters / coin (driven by primitives, but available raw):**
- `.ax-count-up` — CSS-counter tick (set `--ax-count-target`; integer only — for formatted/decimal numbers use the `<CountUp>` component instead).
- `.ax-bar-fill` — animate width once (set `--ax-fill-to`, optional `--ax-fill-from`).
- `.ax-seg-pop` — segmented-cell pop-in (set `--index` for stagger).
- `.ax-coin-flight` — coin flies by `(--ax-coin-x, --ax-coin-y)` over 900ms.

**Semantic verdict classes:** `.ax-verdict-real`, `.ax-verdict-partial`, `.ax-verdict-fake` — set text color + border + dim wash; pair with `.ax-card-*` for hover glow.

**Form:** `.ax-range` — emerald-thumb range slider track.

**Guards:** `@media (prefers-reduced-motion: reduce)` kills all infinite loops + snaps one-shots/count-up to final frame. A global guard neutralizes `backdrop-filter` (keep backgrounds static; avoid backdrop-blur).

---

## 4. `components/hud/*` primitives

Import everything from the barrel:

```ts
import {
  HudPanel, NeonButton, Eyebrow, GlitchText, CountUp, SegmentBar,
  LiveDot, Stars, CoinFlight,
  Check, Tilde, Cross, Exchange, ArrowRight, ArrowUpRight, Bolt, Coin,
  Gavel, Shield, Clock, Robot, Dot, Star, VerdictGlyph,
} from "@/components/hud";
```

### HudPanel — the framed neon panel (the workhorse container)
```ts
HudPanel(props: {
  children: React.ReactNode;
  title?: React.ReactNode;       // Orbitron heading in the title bar
  eyebrow?: React.ReactNode;     // mono eyebrow above the title
  live?: boolean;                // pulsing live dot in the eyebrow
  right?: React.ReactNode;       // right-aligned header slot (counts/buttons)
  tone?: "default" | "emerald" | "gold" | "red";  // border tint + hover glow color
  hover?: boolean;               // enable lift+glow on hover (clickable cards)
  brackets?: boolean;            // corner HUD ticks (default true)
  padded?: boolean;              // inner body padding (default true; false for self-managed scroll bodies)
  className?: string;
  bodyClassName?: string;
})
```
Header bar renders only if any of `title`/`eyebrow`/`right` are set. Use `padded={false}` when the body has its own scroll regions (see `VerifyPanel`).
**De-green default:** `tone="default"` now uses a **neutral** border (`border-hud-neutral`) and a **muted** header eyebrow — white-led, no emerald veil. Pass `tone="emerald"` to opt back into the emerald hairline (reserve it for real/live panels). The `live` dot still pulses emerald regardless of tone. Title is `text-fg` (white). Corner brackets are a quiet emerald tick on dark and a faint emerald-ink tick on `.ax-light`.

### NeonButton — primary / ghost / danger action
```ts
NeonButton(props: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "danger";  // default "primary"
})
// primary = emerald fill + canvas text + glow on hover; ghost = hairline + emerald text;
// danger = red ghost. scale(0.97) press, visible focus ring. Forwards a ref.
// Theme-aware: on .ax-light the emerald fill deepens to a readable deep-emerald
// with bone text, and ghost/danger text use the deeper accent ink.
```

### Eyebrow — mono uppercase wide-tracked label
```ts
Eyebrow(props: {
  children: React.ReactNode;
  live?: boolean;                                       // leading pulsing dot
  tone?: "emerald" | "gold" | "red" | "muted";          // dot + accent when live
  className?: string;
})
// Default is white-led: the label is muted/neutral (theme-able text-fg-muted).
// An accent color is applied only when BOTH `live` AND a semantic tone are set,
// so accents stay reserved for meaningful streaming rows. Default tone "muted".
```

### GlitchText — display text with hover (or live) glitch
```ts
GlitchText(props: {
  children: React.ReactNode;
  as?: keyof JSX.IntrinsicElements;   // tag to render (default "span")
  live?: boolean;                     // glitch continuously vs only on hover
  className?: string;
})  // renders font-display
```

### CountUp — animated ticking number (rAF; reduced-motion snaps)
```ts
CountUp(props: {
  value: number;
  duration?: number;   // ms, default 1100
  decimals?: number;   // default 0
  prefix?: string;     // e.g. "$"
  suffix?: string;     // e.g. "%"
  className?: string;
})  // re-animates whenever `value` changes; outputs tabular-nums
```

### SegmentBar — segmented (▰▰▰▱) or smooth fill, value 0..1
```ts
SegmentBar(props: {
  value: number;                              // 0..1
  tone?: "emerald" | "gold" | "red";          // default "emerald"
  variant?: "segmented" | "smooth";           // default "segmented"
  segments?: number;                          // cells for segmented (default 12)
  className?: string;
})
```

### LiveDot — pulsing status dot
```ts
LiveDot(props: {
  tone?: "emerald" | "gold" | "red" | "muted";  // default "emerald"
  size?: number;                                // px, default 8
  pulse?: boolean;                              // default true
  className?: string;
})
```

### Stars — fractional reputation stars (neon gold)
```ts
Stars(props: {
  value: number;        // 0..1 (→ 5 stars, fractional last star via clip)
  size?: number;        // px, default 12
  className?: string;
})
```

### CoinFlight — gold coin flies source → target (~900ms)
```ts
CoinFlight(props: {
  dx?: number;      // horizontal travel px, default 140
  dy?: number;      // vertical travel px, default 0
  size?: number;    // default 16
  delay?: number;   // ms, default 0
  className?: string;
})
// Render inside a position:relative parent. Reduced-motion = coin appears at start (no flight).
// Remount it (change its React key) to re-fire.
```

### Icons — one consistent 1.75-stroke SVG set (NO emojis)
All take `{ size?, className?, strokeWidth? }` and inherit `currentColor`:
`Check`, `Tilde`, `Cross`, `Exchange`, `ArrowRight`, `ArrowUpRight`, `Bolt`, `Coin`, `Gavel`, `Shield`, `Clock`, `Robot`, `Dot`, `Star` (`+ filled?`).
`VerdictGlyph({ glyph: "check"|"tilde"|"cross", size?, className? })` picks the verdict glyph (keyed off `lib/ui` `Glyph`).

---

## 5. Reference component — `components/VerifyPanel.tsx`

The HERO of the demo, fully restyled as the gold standard. Built from `HudPanel` (emerald tone, `padded={false}`, `Gavel` title icon, live eyebrow, `VerdictTally` in the right slot), per-finding cards using `SegmentBar` (smooth confidence bar) + `VerdictGlyph` tiles + `verdictStyle()` neon tokens. The FAKE verdict (`unsupported`) is the dramatic red moment: red border + `.ax-card-red` glow, `.ax-glitch-live` label, and a `Withheld · $0` chip. **Its props/export signature are unchanged:** `export function VerifyPanel({ document, findings }: { document: DocumentEvent | null; findings: FindingEvent[] })`. Pattern-match this for the other components.

---

## 6. Demo component signatures (preserve these in Wave 2)

These props are wired by `Dashboard.tsx` — keep them identical when restyling.

```ts
// components/JobCard.tsx
JobCard(props: {
  kind: JobKind; document: string; budget: number;
  demoMode: boolean; running: boolean; loadingSample: boolean;
  onKind: (k: JobKind) => void; onDocument: (d: string) => void;
  onBudget: (b: number) => void; onDemoMode: (v: boolean) => void;
  onRun: () => void;
})

// components/StageBar.tsx
StageBar(props: { stages: StageEvent[] })

// components/BidFeed.tsx
BidFeed(props: {
  pool: PoolAgent[]; bids: BidEvent[];
  hire: HireEvent | null; hiredWorkers: Set<string>;
})

// components/WorkRoom.tsx
WorkRoom(props: { room: RoomLine[] })   // RoomLine from lib/runState

// components/SettleBar.tsx
SettleBar(props: { settlements: SettleEvent[]; done: DoneEvent | null })

// components/Avatar.tsx
Avatar(props: { seed: string; label?: string; size?: number; ring?: boolean })

// components/Stars.tsx  (legacy editorial — prefer @/components/hud Stars)
Stars(props: { value: number })
```

> Note: `lib/ui.ts › avatarColor()` still returns pastel swatches — Wave 2 should re-point `Avatar` (and the legacy `components/Stars.tsx`) to the HUD palette, or swap `components/Stars.tsx` usages for the hud `Stars`. The hud `Stars` is the canonical one. `components/Icons.tsx` (legacy) is superseded by `components/hud/Icons.tsx`; migrate imports and delete the legacy file once nothing references it.
```
