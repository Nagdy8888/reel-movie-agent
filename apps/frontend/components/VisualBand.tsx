import { MaterialIcon } from "./MaterialIcon";

/** Visual band with static chat mockup and entity graph SVG. */
export function VisualBand() {
  return (
    <section
      className="py-24 px-margin-mobile md:px-margin-desktop bg-surface-container-lowest relative z-20 border-t border-hairline"
      id="library"
    >
      <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center gap-xl">
        <div className="w-full md:w-1/2 flex flex-col gap-md">
          <div className="flex justify-end w-full mb-4">
            <div className="bg-surface p-md rounded-xl rounded-tr-sm border border-hairline max-w-[85%] relative overflow-hidden">
              <div className="absolute inset-0 bg-primary/5 pointer-events-none" />
              <p className="font-body-sm text-body-sm text-on-surface relative z-10">
                I&apos;m looking for tense psychological thrillers from the 90s, preferably directed
                by someone who worked with Brad Pitt.
              </p>
            </div>
          </div>
          <div className="flex justify-start w-full">
            <div className="bg-elevated p-md rounded-xl rounded-tl-sm border border-hairline max-w-[95%] shadow-[0_8px_32px_rgba(0,0,0,0.4)]">
              <div className="flex items-center gap-sm mb-md">
                <MaterialIcon name="auto_awesome" className="text-primary text-sm" filled />
                <span className="font-label-caps text-label-caps text-on-surface-variant">
                  REEL INTELLIGENCE
                </span>
              </div>
              <p className="font-body-lg text-body-lg font-display-md text-on-background mb-md">
                Based on your criteria, David Fincher is the primary nexus.
              </p>
              <p className="font-body-sm text-body-sm text-on-surface-variant mb-md leading-relaxed">
                Fincher directed Brad Pitt in{" "}
                <span className="text-on-surface font-semibold border-b border-primary/30 cursor-pointer">
                  Se7en (1995)
                </span>{" "}
                and{" "}
                <span className="text-on-surface font-semibold border-b border-primary/30 cursor-pointer">
                  Fight Club (1999)
                </span>
                . Both fit the psychological thriller archetype perfectly.
              </p>
              <div className="flex gap-sm">
                <span className="px-2 py-1 rounded bg-surface border border-outline-variant/30 text-primary font-label-caps text-[10px]">
                  THRILLER
                </span>
                <span className="px-2 py-1 rounded bg-surface border border-outline-variant/30 text-primary font-label-caps text-[10px]">
                  1990s
                </span>
              </div>
            </div>
          </div>
        </div>
        <div className="w-full md:w-1/2 aspect-square md:aspect-[4/3] rounded-xl border border-hairline bg-canvas relative overflow-hidden shadow-[0_8px_32px_rgba(0,0,0,0.4)] flex items-center justify-center">
          <svg className="w-full h-full absolute inset-0" viewBox="0 0 400 300">
            <line stroke="currentColor" className="text-hairline" strokeWidth="1" x1="200" x2="100" y1="150" y2="80" />
            <line stroke="currentColor" className="text-hairline" strokeWidth="1" x1="200" x2="300" y1="150" y2="80" />
            <line stroke="currentColor" className="text-hairline" strokeWidth="1" x1="200" x2="200" y1="150" y2="250" />
            <line stroke="currentColor" className="text-hairline" strokeWidth="1" x1="200" x2="80" y1="150" y2="200" />
            <line stroke="currentColor" className="text-hairline" strokeWidth="1" x1="200" x2="320" y1="150" y2="200" />
            <g className="node" style={{ animationDelay: "0s" }}>
              <circle cx="200" cy="150" className="fill-primary-container" r="12" />
              <circle cx="200" cy="150" fill="none" opacity="0.3" r="24" className="stroke-primary-container" strokeWidth="1" />
              <text fill="currentColor" className="text-on-surface" fontFamily="var(--font-inter)" fontSize="10" fontWeight="600" textAnchor="middle" x="200" y="185">
                David Fincher
              </text>
              <text fill="currentColor" className="text-on-surface-variant" fontFamily="var(--font-inter)" fontSize="8" fontWeight="400" textAnchor="middle" x="200" y="198">
                DIRECTOR
              </text>
            </g>
            <g className="node" style={{ animationDelay: "0.2s" }}>
              <circle cx="100" cy="80" className="fill-surface-tint" r="6" />
              <text fill="currentColor" className="text-on-surface" fontFamily="var(--font-inter)" fontSize="10" textAnchor="middle" x="100" y="65">
                Se7en
              </text>
            </g>
            <g className="node" style={{ animationDelay: "0.4s" }}>
              <circle cx="300" cy="80" className="fill-surface-tint" r="6" />
              <text fill="currentColor" className="text-on-surface" fontFamily="var(--font-inter)" fontSize="10" textAnchor="middle" x="300" y="65">
                Brad Pitt
              </text>
            </g>
            <g className="node" style={{ animationDelay: "0.6s" }}>
              <circle cx="200" cy="250" className="fill-surface-tint" r="6" />
              <text fill="currentColor" className="text-on-surface" fontFamily="var(--font-inter)" fontSize="10" textAnchor="middle" x="200" y="270">
                Thriller
              </text>
            </g>
            <g className="node" style={{ animationDelay: "0.8s" }}>
              <circle cx="80" cy="200" className="fill-on-surface-variant" opacity="0.6" r="4" />
            </g>
            <g className="node" style={{ animationDelay: "1s" }}>
              <circle cx="320" cy="200" className="fill-on-surface-variant" opacity="0.6" r="4" />
            </g>
          </svg>
        </div>
      </div>
    </section>
  );
}
