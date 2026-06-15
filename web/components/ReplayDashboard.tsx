"use client";

import { useCallback, useRef } from "react";
import { useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";
import { useReplay } from "@/lib/useReplay";
import { scrollIntoFullView } from "@/lib/scroll";
import { WorkRoom } from "@/components/WorkRoom";
import {
  Eyebrow,
  GlitchText,
  NeonButton,
  LiveDot,
  Exchange,
  Narrator,
} from "@/components/hud";

// ── Arena: client-only, mirrors Dashboard.tsx's import pattern exactly ──────
// Dashboard does: import("./arena").then(m => m.Arena) from within /components.
// We're in /components too, so the same relative path works. However, using the
// absolute alias is clearer and equally correct.
const Arena = dynamic(
  () => import("@/components/arena").then((m) => m.Arena),
  {
    ssr: false,
    loading: () => (
      <div
        className="flex w-full items-center justify-center"
        style={{ aspectRatio: "1 / 1", maxHeight: 480 }}
      >
        <div
          aria-hidden
          className="rounded-full border border-hud-neutral"
          style={{ width: "45%", aspectRatio: "1 / 1", opacity: 0.4 }}
        />
      </div>
    ),
  }
);

const DEFAULT_JOB_ID = "sim-contract-audit-seeded-liar";

const SAMPLE_REPLAYS = [
  {
    label: "Contract Audit · Seeded Liar",
    url: "/replays/sim-contract-audit-seeded-liar.replay.json",
  },
  {
    label: "NDA Review · Seeded Liar",
    url: "/replays/sim-nda-review-seeded-liar.replay.json",
  },
] as const;

export function ReplayDashboard() {
  // ── Derive autoload URL from ?job= search param ────────────────────────────
  const params = useSearchParams();
  const jobId = params.get("job") ?? DEFAULT_JOB_ID;
  const autoloadUrl = `/replays/${jobId}.replay.json`;

  const ctl = useReplay({ autoloadUrl });

  // ── File drop / pick handlers ──────────────────────────────────────────────
  const fileInputRef = useRef<HTMLInputElement>(null);

  // The arena section — framed fully into view when playback starts.
  const arenaRef = useRef<HTMLElement>(null);
  const onPlayPause = useCallback(() => {
    const wasPlaying = ctl.playing;
    ctl.toggle();
    // Only frame the arena when STARTING playback (not when pausing).
    if (!wasPlaying) scrollIntoFullView(arenaRef.current);
  }, [ctl]);

  const handleFilePick = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) void ctl.loadFromFile(file);
      // Reset the input so the same file can be picked again.
      e.target.value = "";
    },
    [ctl]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      const file = e.dataTransfer.files[0];
      if (file) void ctl.loadFromFile(file);
    },
    [ctl]
  );

  const handleDragOver = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
  }, []);

  const loaded = ctl.status === "loaded";
  const scrubberMax = Math.max(0, ctl.total - 1);
  const scrubberValue = Math.max(0, ctl.cursor);

  // Lift the Band-room transcript while the Work stage is the active beat.
  const workActive =
    ctl.state.stages.find((s) => s.status === "active")?.name === "Work";

  return (
    <main className="ax-stage mx-auto flex min-h-screen max-w-[1240px] flex-col gap-10 px-6 py-12 lg:px-8 lg:py-16">
      {/* ── Masthead ───────────────────────────────────────────────────── */}
      <header className="flex flex-wrap items-end justify-between gap-5 border-b border-hud-neutral pb-8">
        <div className="flex items-center gap-4">
          <div className="flex h-11 w-11 items-center justify-center rounded-lg border border-hud-neutral bg-surface-2 text-fg">
            <Exchange size={22} />
          </div>
          <div>
            <Eyebrow live tone="gold">
              JOB REPLAY
            </Eyebrow>
            <GlitchText
              as="h1"
              className="mt-1.5 text-[24px] font-black uppercase tracking-[0.04em] text-fg"
            >
              Agent Exchange
            </GlitchText>
            <p className="mt-1.5 max-w-xl font-mono text-[12.5px] leading-relaxed text-fg-muted">
              Scrub through a recorded run — every event, every verdict, every
              payment.
            </p>
          </div>
        </div>
        {/* Mode pill — gold LiveDot for REPLAY (mirrors Dashboard's demo pill) */}
        <div className="flex items-center gap-2.5 font-mono text-[11px]">
          <span className="inline-flex items-center gap-2 rounded-md border border-hud-neutral bg-surface px-3 py-1.5 text-fg-muted">
            <LiveDot tone="gold" size={7} />
            REPLAY
          </span>
        </div>
      </header>

      {/* ── Narrator ──────────────────────────────────────────────────── */}
      <Narrator
        stages={ctl.state.stages}
        running={ctl.state.running}
        finished={ctl.state.finished}
        alwaysOn={loaded}
        idlePlaceholder={
          loaded
            ? "Use the transport bar to play the replay."
            : "Load a replay file to begin."
        }
      />

      {/* ── JOB strip (mirrors Dashboard's collapsed-console strip) ──── */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-hud-neutral bg-surface px-4 py-2.5 font-mono text-[11px] text-fg-muted">
        <span className="inline-flex items-center gap-2">
          <Eyebrow tone="muted">JOB</Eyebrow>
          <span className="text-fg">{ctl.meta?.title ?? "—"}</span>
        </span>
        <span className="inline-flex items-center gap-3">
          {ctl.meta?.budget_usd !== undefined ? (
            <span className="tabular-nums text-gold">
              ${ctl.meta.budget_usd.toFixed(2)} bounty
            </span>
          ) : (
            <span className="tabular-nums text-fg-faint">— bounty</span>
          )}
        </span>
      </div>

      {/* ── Error box (mirrors Dashboard's error box styling) ─────────── */}
      {ctl.status === "error" && ctl.error && (
        <div
          className="ax-fade-up flex flex-wrap items-center gap-x-2 rounded-lg border border-danger/40 px-4 py-3 font-mono text-[12.5px] text-danger"
          style={{ background: "rgba(255,59,92,0.06)" }}
        >
          <span className="font-display font-bold uppercase tracking-[0.08em]">
            Error
          </span>
          <span className="text-fg-muted">{ctl.error}</span>
        </div>
      )}

      {/* ── Loader (when not yet loaded) ─────────────────────────────── */}
      {!loaded && (
        <section className="flex flex-col gap-6">
          <Eyebrow tone="muted">Load a replay</Eyebrow>

          {/* Drop zone */}
          <div
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            onClick={() => fileInputRef.current?.click()}
            className="flex cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-hud-neutral bg-surface px-8 py-12 text-center transition-colors hover:border-emerald hover:bg-emerald-dim"
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                fileInputRef.current?.click();
              }
            }}
            aria-label="Drop a replay JSON file here or click to pick one"
          >
            <span className="font-mono text-[13px] font-medium text-fg-muted">
              Drop a{" "}
              <code className="rounded bg-surface-2 px-1 py-0.5 text-fg">
                .replay.json
              </code>{" "}
              here
            </span>
            <span className="font-mono text-[11px] text-fg-faint">
              or click to pick a file
            </span>
            {ctl.status === "loading" && (
              <span className="mt-2 inline-flex items-center gap-2 font-mono text-[11px] text-gold">
                <LiveDot tone="gold" size={6} />
                Loading…
              </span>
            )}
          </div>

          {/* Hidden file input */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".json,application/json"
            className="hidden"
            onChange={handleFilePick}
            aria-hidden="true"
            tabIndex={-1}
          />

          {/* Bundled samples */}
          <div className="flex flex-col gap-3">
            <Eyebrow tone="muted">bundled samples</Eyebrow>
            <div className="flex flex-wrap gap-3">
              {SAMPLE_REPLAYS.map((s) => (
                <NeonButton
                  key={s.url}
                  variant="ghost"
                  onClick={() => void ctl.loadFromUrl(s.url)}
                  disabled={ctl.status === "loading"}
                >
                  {s.label}
                </NeonButton>
              ))}
            </div>
          </div>
        </section>
      )}

      {/* ── Transport bar (when loaded) ───────────────────────────────── */}
      {loaded && (
        <section
          className="flex flex-col gap-3 rounded-xl border border-hud-neutral bg-surface px-4 py-3"
          aria-label="Replay transport controls"
        >
          {/* Controls row */}
          <div className="flex flex-wrap items-center gap-2">
            {/* Step back — C1: h-10 w-10 = 40px hit area */}
            <button
              type="button"
              onClick={ctl.stepBack}
              aria-label="Step back"
              className="ax-press inline-flex h-10 w-10 items-center justify-center rounded-md border border-hud-neutral bg-surface-2 font-mono text-[14px] text-fg-muted transition hover:border-emerald hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald/70"
            >
              ◀
            </button>

            {/* Play / Pause toggle — C1: h-10 w-10 = 40px hit area */}
            <button
              type="button"
              onClick={onPlayPause}
              aria-label={ctl.playing ? "Pause" : "Play"}
              className="ax-press inline-flex h-10 w-10 items-center justify-center rounded-md border border-hud-neutral bg-surface-2 font-mono text-[14px] text-fg-muted transition hover:border-emerald hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald/70"
            >
              {ctl.playing ? "⏸" : "▶"}
            </button>

            {/* Step forward — C1: h-10 w-10 = 40px hit area */}
            <button
              type="button"
              onClick={ctl.stepFwd}
              aria-label="Step forward"
              className="ax-press inline-flex h-10 w-10 items-center justify-center rounded-md border border-hud-neutral bg-surface-2 font-mono text-[14px] text-fg-muted transition hover:border-emerald hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald/70"
            >
              ▶▶
            </button>

            {/* Scrubber */}
            <input
              type="range"
              min={0}
              max={scrubberMax}
              value={scrubberValue}
              onChange={(e) => ctl.seek(Number(e.target.value))}
              aria-label="Replay scrubber"
              className="mx-1 h-1.5 flex-1 cursor-pointer appearance-none rounded-full bg-hud-neutral accent-emerald"
              style={{ minWidth: 80 }}
            />

            {/* Speed chip — C2: tabular-nums so width is stable across 0.5/1/2/4 */}
            <button
              type="button"
              onClick={ctl.cycleSpeed}
              aria-label={`Playback speed ${ctl.speed}×, click to cycle`}
              className="ax-press inline-flex h-7 items-center rounded-md border border-hud-neutral bg-surface-2 px-2.5 font-mono text-[11px] text-fg-muted transition hover:border-gold hover:text-gold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald/70"
            >
              <span className="tabular-nums">{ctl.speed}×</span>
            </button>

            {/* Jump to catch — C5: primary (emerald fill) — the one clear CTA */}
            <NeonButton
              variant="primary"
              onClick={ctl.jumpToCatch}
              className="text-[11px]"
            >
              ⏭ Jump to the catch
            </NeonButton>

            {/* Restart — stays ghost */}
            <NeonButton
              variant="ghost"
              onClick={ctl.restart}
              className="text-[11px]"
            >
              ↻ restart
            </NeonButton>
          </div>

          {/* Readout row */}
          <div className="flex items-center gap-3 font-mono text-[11px] text-fg-faint">
            <span className="tabular-nums">
              {ctl.cursor + 1} / {ctl.total}
            </span>
            <span className="text-hud-neutral">·</span>
            <span className="text-fg-muted">{ctl.currentType ?? "—"}</span>
          </div>
        </section>
      )}

      {/* ── The arena section — mirrors Dashboard's "02 · THE ARENA" exactly ── */}
      <section ref={arenaRef} className="flex flex-col gap-4 scroll-mt-6">
        <Eyebrow tone="muted">The arena</Eyebrow>
        {/* Ring + live Band-room transcript side-by-side, same as the live demo,
            so a replay reads as agents conversing in one room too. */}
        <div className="ax-court px-3 py-6 sm:px-6 sm:py-8">
          <div className="grid items-stretch gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(300px,380px)]">
            <Arena state={ctl.state} idleHint="Press ▶ to play the recorded run" />
            <WorkRoom room={ctl.state.room} workActive={workActive} />
          </div>
        </div>
      </section>

      <footer className="border-t border-hud-neutral pt-7 text-center font-mono text-[11px] uppercase tracking-[0.08em] text-fg-faint">
        bid · hire · work · a calibrated verifier proves the work · USDC settles
        only on proof
      </footer>
    </main>
  );
}
