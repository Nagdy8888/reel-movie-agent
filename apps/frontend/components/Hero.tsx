import Link from "next/link";
import { MaterialIcon } from "./MaterialIcon";

/** Landing page hero section with decorative graph overlay. */
export function Hero() {
  return (
    <section className="relative z-10 w-full min-h-[90vh] flex flex-col items-center justify-center px-margin-mobile md:px-margin-desktop py-xl overflow-hidden hero-gradient">
      <div className="absolute inset-0 z-10 pointer-events-none opacity-30">
        <svg className="w-full h-full" preserveAspectRatio="xMidYMid slice" viewBox="0 0 1000 1000">
          <line stroke="currentColor" className="text-hairline" strokeWidth="0.5" x1="200" x2="500" y1="300" y2="500" />
          <line stroke="currentColor" className="text-hairline" strokeWidth="0.5" x1="800" x2="500" y1="200" y2="500" />
          <line stroke="currentColor" className="text-hairline" strokeWidth="0.5" x1="500" x2="400" y1="500" y2="800" />
          <line stroke="currentColor" className="text-hairline" strokeWidth="0.5" x1="500" x2="700" y1="500" y2="700" />
          <circle className="node fill-primary-container" cx="200" cy="300" r="4" />
          <circle className="node fill-primary-container" cx="800" cy="200" r="6" />
          <circle className="node fill-primary-container" cx="500" cy="500" r="8" />
          <circle className="node fill-primary-container" cx="400" cy="800" r="5" />
          <circle className="node fill-primary-container" cx="700" cy="700" r="4" />
        </svg>
      </div>
      <div className="relative z-20 max-w-4xl mx-auto text-center flex flex-col items-center gap-xl mt-xl">
        <h1 className="font-display-lg text-display-lg md:text-[72px] md:leading-[1.1] text-on-background tracking-tight max-w-3xl">
          Ask anything about movies.
        </h1>
        <p className="font-body-lg text-body-lg md:text-[20px] text-on-surface-variant max-w-2xl leading-relaxed">
          Reel understands cast, genres, plots, and box office — and connects the dots across a
          film knowledge graph.
        </p>
        <div className="flex flex-col sm:flex-row gap-md mt-md">
          <Link
            href="/login"
            className="bg-primary-container text-on-primary-container font-title-md text-title-md px-xl py-md rounded font-semibold hover:brightness-110 transition-all shadow-[0_0_20px_rgba(232,180,87,0.2)] text-center"
          >
            Start chatting
          </Link>
          <Link
            href="/login?demo=1"
            className="bg-transparent text-inverse-surface border border-hairline font-title-md text-title-md px-xl py-md rounded font-semibold hover:bg-surface-variant/50 transition-all text-center"
          >
            See a demo
          </Link>
        </div>
        <div className="w-full max-w-2xl mt-xl p-xs rounded-xl bg-canvas/90 border border-hairline shadow-[0_8px_32px_rgba(0,0,0,0.4)] flex items-center relative group hover:border-primary/50 transition-colors duration-500">
          <div className="absolute -inset-0.5 bg-primary/20 rounded-xl blur opacity-0 group-hover:opacity-100 transition duration-500 pointer-events-none" />
          <div className="relative w-full flex items-center bg-canvas/90 rounded-lg px-md py-sm">
            <MaterialIcon name="movie_filter" className="text-on-surface-variant mr-md" />
            <input
              className="w-full bg-transparent border-none text-body-lg text-on-surface focus:ring-0 placeholder:text-outline-variant outline-none"
              disabled
              placeholder="Sci-fi movies about survival, or who starred in..."
              type="text"
            />
            <button type="button" className="bg-surface-variant p-sm rounded-md text-primary ml-md" disabled>
              <MaterialIcon name="arrow_upward" filled />
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
