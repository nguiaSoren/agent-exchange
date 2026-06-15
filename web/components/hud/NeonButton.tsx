import { forwardRef } from "react";

type Variant = "primary" | "ghost" | "danger";

/**
 * NeonButton — the HUD action control.
 *   primary — emerald fill, black text, glow on hover
 *   ghost   — hairline border, emerald text, fills dim on hover
 *   danger  — red-tinted ghost (destructive / withhold actions)
 * scale(0.97) on press, visible focus ring.
 */
export interface NeonButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
}

const VARIANT: Record<Variant, string> = {
  primary:
    "bg-emerald text-canvas font-display font-bold border border-emerald hover:shadow-glow-emerald hover:bg-emerald-glow",
  ghost:
    "bg-transparent text-emerald-glow border border-hud hover:border-emerald hover:bg-emerald-dim",
  danger:
    "bg-transparent text-danger border border-danger/60 hover:border-danger hover:bg-danger-dim",
};

export const NeonButton = forwardRef<HTMLButtonElement, NeonButtonProps>(
  function NeonButton(
    { variant = "primary", className = "", children, ...rest },
    ref
  ) {
    return (
      <button
        ref={ref}
        className={`ax-press inline-flex items-center justify-center gap-2 rounded-md px-5 py-2.5 text-[12px] font-medium uppercase tracking-[0.12em] outline-none transition focus-visible:ring-2 focus-visible:ring-emerald/70 focus-visible:ring-offset-2 focus-visible:ring-offset-canvas disabled:cursor-not-allowed disabled:opacity-45 ${VARIANT[variant]} ${className}`}
        {...rest}
      >
        {children}
      </button>
    );
  }
);
