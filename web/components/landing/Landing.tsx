import { Topbar } from "./Topbar";
import { Hero } from "./Hero";
import { HeroShotWithheld } from "./HeroShotWithheld";
import { HeroShotRecruit } from "./HeroShotRecruit";
import { HowItWorks } from "./HowItWorks";
import { Numbers } from "./Numbers";
import { Research } from "./Research";
import { ClosingCTA } from "./ClosingCTA";
import { Footer } from "./Footer";

/**
 * Landing — the concept landing page for The Agent Exchange.
 * Reads top-to-bottom: topbar → hero → the two HERO SHOTS (the catch → $0, and
 * cross-owner recruitment) → how it works → numbers → research/proof → closing
 * CTA → footer.
 */
export function Landing() {
  return (
    <>
      <Topbar />
      <main>
        <Hero />
        <HeroShotWithheld />
        <HeroShotRecruit />
        <HowItWorks />
        <Numbers />
        <Research />
        <ClosingCTA />
      </main>
      <Footer />
    </>
  );
}
