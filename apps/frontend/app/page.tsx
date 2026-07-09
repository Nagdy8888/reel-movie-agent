import { TopNavBar } from "@/components/TopNavBar";
import { Hero } from "@/components/Hero";
import { HowItWorks } from "@/components/HowItWorks";
import { FeatureGrid } from "@/components/FeatureGrid";
import { VisualBand } from "@/components/VisualBand";
import { Footer } from "@/components/Footer";

/** Marketing landing page — static content, not wired to the backend. */
export default function LandingPage() {
  return (
    <div className="text-on-background font-body-lg min-h-screen flex flex-col">
      <TopNavBar />
      <main className="flex-grow pt-24">
        <Hero />
        <HowItWorks />
        <FeatureGrid />
        <VisualBand />
      </main>
      <Footer />
    </div>
  );
}
