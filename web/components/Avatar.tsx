"use client";

import { avatarColor, initials } from "@/lib/ui";

export function Avatar({
  seed,
  label,
  size = 34,
  ring = false,
}: {
  seed: string;
  label?: string;
  size?: number;
  ring?: boolean;
}) {
  const { bg, fg } = avatarColor(seed);
  return (
    <div
      className="flex shrink-0 items-center justify-center rounded-md font-display font-bold uppercase tracking-[0.04em]"
      style={{
        width: size,
        height: size,
        background: bg,
        color: fg,
        fontSize: size * 0.34,
        boxShadow: ring
          ? `inset 0 0 0 1px ${fg}88, 0 0 0 1.5px ${fg}, 0 0 12px -2px ${fg}`
          : `inset 0 0 0 1px ${fg}33`,
      }}
      title={label ?? seed}
      aria-hidden
    >
      {initials(label ?? seed)}
    </div>
  );
}
