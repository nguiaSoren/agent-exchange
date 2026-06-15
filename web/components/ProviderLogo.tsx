"use client";

import { useState } from "react";
import { Featherless } from "@lobehub/icons";

import { logoFor, type Gateway, type ProviderRecord } from "@/lib/providers";

/**
 * Renders an agent's AI-model brand logo as a small colored badge, suitable for
 * placing on a dark arena node. Uses the brand's `.Avatar` variant from
 * `@lobehub/icons` (a brand-colored rounded mark).
 *
 * Usage: `<ProviderLogo provider={rec} size={20} />`
 */
export function ProviderLogo({
  provider,
  size = 20,
  title,
}: {
  provider: ProviderRecord;
  size?: number;
  /** Accessible label; defaults to the provider label. */
  title?: string;
}) {
  const Logo = logoFor(provider);
  return (
    <span
      className="inline-flex shrink-0 items-center justify-center"
      title={title ?? provider.providerLabel}
      aria-label={title ?? `${provider.providerLabel} logo`}
    >
      <Logo size={size} />
    </span>
  );
}

/**
 * Renders the SPONSOR/gateway mark (the partner the agent is routed through),
 * not the model brand — used on the cross-framework nodes so the AI/ML API and
 * Featherless logos sit on their corresponding agents. Featherless ships a real
 * `.Avatar` in `@lobehub/icons`; AI/ML API has no lobehub logo, so its official
 * mark (`/sponsors/aimlapi.png`) is rendered in a matching rounded badge with a
 * text-wordmark fallback if the asset is ever missing.
 *
 * Usage: `<GatewayLogo gateway="AI/ML API" size={28} />`
 */
export function GatewayLogo({
  gateway,
  size = 20,
}: {
  gateway: Gateway;
  size?: number;
}) {
  const [failed, setFailed] = useState(false);

  if (gateway === "Featherless") {
    return (
      <span
        className="inline-flex shrink-0 items-center justify-center"
        title="Featherless (open-weight inference)"
        aria-label="Featherless logo"
      >
        <Featherless.Avatar size={size} />
      </span>
    );
  }

  if (gateway === "AI/ML API") {
    if (failed) {
      return (
        <span
          className="inline-flex shrink-0 items-center justify-center rounded-[24%] bg-white px-1 font-bold leading-none text-black"
          style={{ width: size, height: size, fontSize: Math.round(size * 0.24) }}
          title="AI/ML API"
        >
          AI/ML
        </span>
      );
    }
    return (
      <span
        className="inline-flex shrink-0 items-center justify-center rounded-[24%] bg-white"
        style={{ width: size, height: size }}
        title="AI/ML API (model gateway)"
        aria-label="AI/ML API logo"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/sponsors/aimlapi.png"
          alt="AI/ML API"
          width={Math.round(size * 0.8)}
          height={Math.round(size * 0.8)}
          onError={() => setFailed(true)}
        />
      </span>
    );
  }

  // OpenAI / any other gateway has no dedicated sponsor mark — caller should use
  // ProviderLogo for those; render nothing rather than a wrong badge.
  return null;
}
