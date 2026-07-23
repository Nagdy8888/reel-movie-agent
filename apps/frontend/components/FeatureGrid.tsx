import { MaterialIcon } from "./MaterialIcon";

interface FeatureCardProps {
  icon: string;
  title: string;
  description: React.ReactNode;
}

function FeatureCard({ icon, title, description }: FeatureCardProps) {
  return (
    <div className="bg-surface-container-low p-xl rounded-xl border border-hairline flex flex-col justify-between group overflow-hidden relative">
      <div className="absolute right-0 top-0 w-32 h-32 bg-primary/5 rounded-bl-full blur-xl group-hover:bg-primary/10 transition-colors" />
      <div className="relative z-10">
        <MaterialIcon name={icon} className="text-primary mb-md text-2xl" />
        <h3 className="font-headline-lg text-headline-lg text-on-background mb-sm">{title}</h3>
        <p className="font-body-lg text-body-lg text-on-surface-variant">{description}</p>
      </div>
    </div>
  );
}

/** Feature grid section for the landing page. */
export function FeatureGrid() {
  return (
    <section className="py-24 px-margin-mobile md:px-margin-desktop bg-transparent relative z-20" id="features">
      <div className="max-w-7xl mx-auto">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-lg">
          <FeatureCard
            icon="hub"
            title="Knowledge-graph answers"
            description="Move beyond keyword search. Explore how movies connect through cast, genres, characters, and plot themes."
          />
          <FeatureCard
            icon="verified"
            title="Cited sources you can trust"
            description={
              <>
                Every claim is backed by citations from reputable databases. Click any{" "}
                <span className="inline-block px-2 py-0.5 rounded-full bg-surface-variant/50 text-primary font-label-caps text-[10px] ml-1 mr-1 border border-hairline">
                  SOURCE
                </span>{" "}
                to verify.
              </>
            }
          />
          <FeatureCard
            icon="search_insights"
            title="Semantic + structured"
            description={
              <>
                Combine exact filters (&quot;Release year &lt; 1980&quot;) with fuzzy concepts
                (&quot;neo-noir atmosphere&quot;).
              </>
            }
          />
          <FeatureCard
            icon="favorite"
            title="Remembers your taste"
            description="Build your personal cinema profile. Reel learns your preferences to offer bespoke discovery paths."
          />
        </div>
      </div>
    </section>
  );
}
