import { Landing } from "@/components/landing/Landing";
import { Dashboard } from "@/components/Dashboard";
import { HashScroll } from "@/components/HashScroll";

export default function Home() {
  return (
    <>
      {/* Corrects a deep link like /#try-it-live once the hero shots + fonts
          above the target finish laying out (the native anchor jump fires too
          early and lands short). No-op when there is no hash. */}
      <HashScroll />
      {/* Dark operator-terminal landing — every token + hud primitive resolves to
          the neon-on-near-black HUD; the body grid/spotlight/scanlines show through
          for depth. */}
      <div className="text-fg">
        <Landing />
      </div>
      {/* The live demo shares the same dark world — the agent arena is now native
          to the page, not an inset on a light surface. */}
      <section id="live-run">
        <Dashboard />
      </section>
    </>
  );
}
