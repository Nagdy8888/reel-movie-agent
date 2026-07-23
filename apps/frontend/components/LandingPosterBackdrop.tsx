import Image from "next/image";

const PAGE_POSTERS = [
  {
    src: "https://image.tmdb.org/t/p/w500/1pdfLvkbY9ohJlCjQH2CZjjYVvJ.jpg",
    className: "right-[-2%] top-[3%] h-[420px] w-[280px] rotate-[5deg] sm:right-[4%]",
  },
  {
    src: "https://image.tmdb.org/t/p/w500/gEU2QniE6E77NI6lCU6MxlNBvIx.jpg",
    className: "left-[-4%] top-[6%] h-[380px] w-[250px] -rotate-[7deg] sm:left-[2%]",
  },
  {
    src: "https://image.tmdb.org/t/p/w500/qJ2tW6WMUDux911r6m7haRef0WH.jpg",
    className: "right-[8%] top-[20%] h-[360px] w-[240px] rotate-[8deg]",
  },
  {
    src: "https://image.tmdb.org/t/p/w500/8Gxv8gSFCU0XGDykEGv7zR1n2ua.jpg",
    className: "left-[6%] top-[26%] h-[340px] w-[230px] -rotate-[4deg]",
  },
  {
    src: "https://image.tmdb.org/t/p/w500/f89U3ADr1oiB1s9GkdPOEpXUk5H.jpg",
    className: "right-[-1%] top-[40%] h-[380px] w-[250px] -rotate-[3deg] sm:right-[6%]",
  },
  {
    src: "https://image.tmdb.org/t/p/w500/udDclJoHjfjb8Ekgsd4FDteOkCU.jpg",
    className: "left-[-2%] top-[46%] h-[350px] w-[230px] rotate-[6deg] sm:left-[8%]",
  },
  {
    src: "https://image.tmdb.org/t/p/w500/7IiTTgloJzvGI1TAYymCfbfl3vT.jpg",
    className: "right-[10%] top-[60%] h-[340px] w-[220px] rotate-[4deg]",
  },
  {
    src: "https://image.tmdb.org/t/p/w500/pB8BM7pdSp6B6Ih7QZ4DrQ3PmJK.jpg",
    className: "left-[8%] top-[70%] h-[360px] w-[240px] -rotate-[6deg]",
  },
  {
    src: "https://image.tmdb.org/t/p/w500/1pdfLvkbY9ohJlCjQH2CZjjYVvJ.jpg",
    className: "right-[4%] top-[82%] h-[320px] w-[210px] rotate-[7deg]",
  },
] as const;

/** Dimmed, page-tall poster field that scrolls with the landing page. */
export function LandingPosterBackdrop() {
  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-0 z-0 overflow-hidden">
      {PAGE_POSTERS.map((poster, index) => (
        <div
          key={`${poster.src}-${index}`}
          className={`absolute overflow-hidden rounded-2xl opacity-45 shadow-[0_24px_80px_rgba(0,0,0,0.75)] ${poster.className}`}
        >
          <Image
            src={poster.src}
            alt=""
            fill
            sizes="280px"
            unoptimized
            priority={index < 4}
            className="object-cover brightness-[0.55] saturate-[0.7]"
          />
          <div className="absolute inset-0 bg-gradient-to-t from-canvas/70 via-canvas/15 to-transparent" />
        </div>
      ))}
      {/* Soft center wash so copy stays readable without wiping posters out */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(14,14,17,0.55)_0%,rgba(14,14,17,0.15)_55%,transparent_75%)]" />
    </div>
  );
}
