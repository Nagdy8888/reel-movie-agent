import { MaterialIcon } from "./MaterialIcon";

interface HowItWorksCardProps {
  icon: string;
  title: string;
  description: string;
}

function HowItWorksCard({ icon, title, description }: HowItWorksCardProps) {
  return (
    <div className="glass-panel p-xl flex flex-col items-center text-center rounded-xl hover:translate-y-[-4px] transition-transform duration-300">
      <div className="w-16 h-16 rounded-full bg-surface-variant flex items-center justify-center mb-lg gold-glow">
        <MaterialIcon name={icon} className="text-primary text-3xl" filled />
      </div>
      <h3 className="font-title-md text-title-md text-on-background mb-sm">{title}</h3>
      <p className="font-body-sm text-body-sm text-on-surface-variant">{description}</p>
    </div>
  );
}

/** Three-step explainer section for the landing page. */
export function HowItWorks() {
  return (
    <section
      className="py-24 px-margin-mobile md:px-margin-desktop bg-surface-container-lowest/35 relative z-20"
      id="discover"
    >
      <div className="max-w-7xl mx-auto">
        <div className="text-center mb-16">
          <h2 className="font-headline-lg text-headline-lg text-on-background">How Reel Works</h2>
          <div className="w-12 h-1 bg-primary mx-auto mt-6" />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-lg">
          <HowItWorksCard
            icon="chat_bubble"
            title="Ask a question"
            description="Describe a mood, a half-remembered plot, or specific cinematic criteria in natural language."
          />
          <HowItWorksCard
            icon="account_tree"
            title="Traverse the Graph"
            description="Reel's intelligence analyzes connections between millions of entities across cinematic history."
          />
          <HowItWorksCard
            icon="auto_awesome_motion"
            title="Get Answers"
            description="Receive curated, highly accurate recommendations and insights backed by reliable citations."
          />
        </div>
      </div>
    </section>
  );
}
