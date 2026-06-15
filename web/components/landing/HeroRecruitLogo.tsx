"use client";

import { ProviderLogo } from "@/components/ProviderLogo";
import { resolveProvider } from "@/lib/providers";

/**
 * Client-only provider logo for the recruit hero scene. Isolated into its own
 * module so HeroShotRecruit can load it via `dynamic(ssr:false)` — that keeps
 * the `@lobehub/icons` brand barrel (NOT prerender-safe, same reason the arena
 * is ssr:false) entirely OUT of the landing page's static SSR module graph.
 */
export function HeroRecruitLogo({
  providerKey,
  size = 34,
}: {
  providerKey: string;
  size?: number;
}) {
  return <ProviderLogo provider={resolveProvider(providerKey)} size={size} />;
}
