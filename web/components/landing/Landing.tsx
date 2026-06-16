import { Topbar } from "./Topbar";
import { Hero } from "./Hero";
import { HeroShotRoom } from "./HeroShotRoom";
import { HeroShotRecruit } from "./HeroShotRecruit";
import { HeroShotInsurance } from "./HeroShotInsurance";
import { HowItWorks } from "./HowItWorks";
import { Numbers } from "./Numbers";
import { Research } from "./Research";
import { Governance } from "./Governance";
import { TryItLive } from "./TryItLive";
import { ClosingCTA } from "./ClosingCTA";
import { BuiltOnBand } from "./BuiltOnBand";
import { Footer } from "./Footer";

/**
 * Landing — the concept landing page for The Agent Exchange.
 * Reads top-to-bottom: topbar → hero → the HERO SHOTS (the live Band room leads,
 * then cross-owner recruit, then the insurance catch → $0) → what happens in the room →
 * numbers → research/proof → governance (permission & proof) → run-it-live-in-a-
 * real-Band-room (the LIVE judge path) → closing CTA → built-on-Band → footer.
 */
export function Landing() {
  return (
    <>
      <Topbar />
      <main>
        <Hero />
        <HeroShotRoom />
        <HeroShotRecruit />
        <HeroShotInsurance />
        <HowItWorks />
        <Numbers />
        <Research />
        <Governance />
        <TryItLive />
        <ClosingCTA />
        <BuiltOnBand />
      </main>
      <Footer />
    </>
  );
}
