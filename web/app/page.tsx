import { Landing } from "@/components/landing/Landing";
import { Dashboard } from "@/components/Dashboard";

export default function Home() {
  return (
    <>
      {/* White / bone editorial landing — the .ax-light scope re-themes every
          token + hud primitive to the light surface; bg-canvas paints over the
          body's dark grid for a clean white field. */}
      <div className="ax-light bg-canvas text-fg">
        <Landing />
      </div>
      {/* The demo is a white .ax-light surface (cohesive with the landing); the
          agent arena sits on a light .ax-court stadium inset, with its nodes,
          edges, particles and coins carrying the vivid signal accents. */}
      <section id="live-run">
        <Dashboard />
      </section>
    </>
  );
}
