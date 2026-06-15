import { Suspense } from "react";
import { ReplayDashboard } from "@/components/ReplayDashboard";

/**
 * /replay — server component wrapper.
 *
 * Mirrors the outer theming of app/page.tsx's Dashboard section:
 *   .ax-light  — the white/bone surface token channel
 *   bg-canvas  — paints the body's dark grid clean
 * ReplayDashboard is a "use client" component that reads ?job= via
 * useSearchParams (which requires Suspense; we wrap it here).
 */
export default function ReplayPage() {
  return (
    <div className="ax-light bg-canvas text-fg">
      <section id="replay-run">
        <Suspense
          fallback={
            <div className="flex min-h-screen items-center justify-center font-mono text-[12px] text-fg-faint">
              Loading replay…
            </div>
          }
        >
          <ReplayDashboard />
        </Suspense>
      </section>
    </div>
  );
}
