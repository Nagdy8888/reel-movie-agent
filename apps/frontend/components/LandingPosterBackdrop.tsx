import Image from "next/image";

const PAGE_POSTERS = [
  {
    src: "https://image.tmdb.org/t/p/w500/1pdfLvkbY9ohJlCjQH2CZjjYVvJ.jpg",
    className:
      "hidden sm:block right-[-4%] top-[4%] h-[52vh] w-[38vw] max-w-[360px] rotate-[5deg] opacity-[0.18]",
    sizes: "(max-width: 1024px) 38vw, 360px",
  },
  {
    src: "https://image.tmdb.org/t/p/w500/gEU2QniE6E77NI6lCU6MxlNBvIx.jpg",
    className:
      "hidden md:block left-[-6%] top-[8%] h-[48vh] w-[32vw] max-w-[300px] -rotate-[7deg] opacity-[0.15]",
    sizes: "(max-width: 1280px) 32vw, 300px",
  },
  {
    src: "https://image.tmdb.org/t/p/w500/qJ2tW6WMUDux911r6m7haRef0WH.jpg",
    className:
      "right-[6%] top-[22%] h-[44vh] w-[42vw] max-w-[280px] rotate-[8deg] opacity-[0.14] sm:right-[14%]",
    sizes: "(max-width: 768px) 42vw, 280px",
  },
  {
    src: "https://image.tmdb.org/t/p/w500/8Gxv8gSFCU0XGDykEGv7zR1n2ua.jpg",
    className:
      "hidden lg:block left-[8%] top-[28%] h-[42vh] w-[26vw] max-w-[260px] -rotate-[4deg] opacity-[0.14]",
    sizes: "260px",
  },
  {
    src: "https://image.tmdb.org/t/p/w500/f89U3ADr1oiB1s9GkdPOEpXUk5H.jpg",
    className:
      "hidden md:block right-[-3%] top-[42%] h-[46vh] w-[34vw] max-w-[300px] rotate-[-3deg] opacity-[0.15]",
    sizes: "(max-width: 1280px) 34vw, 300px",
  },
  {
    src: "https://image.tmdb.org/t/p/w500/udDclJoHjfjb8Ekgsd4FDteOkCU.jpg",
    className:
      "left-[-4%] top-[48%] h-[42vh] w-[44vw] max-w-[270px] rotate-[6deg] opacity-[0.13] sm:left-[4%]",
    sizes: "(max-width: 768px) 44vw, 270px",
  },
  {
    src: "https://image.tmdb.org/t/p/w500/7IiTTgloJzvGI1TAYymCfbfl3vT.jpg",
    className:
      "hidden lg:block right-[12%] top-[62%] h-[40vh] w-[24vw] max-w-[250px] rotate-[4deg] opacity-[0.14]",
    sizes: "250px",
  },
  {
    src: "https://image.tmdb.org/t/p/w500/pB8BM7pdSp6B6Ih7QZ4DrQ3PmJK.jpg",
    className:
      "hidden md:block left-[10%] top-[72%] h-[44vh] w-[30vw] max-w-[280px] -rotate-[6deg] opacity-[0.14]",
    sizes: "(max-width: 1280px) 30vw, 280px",
  },
  {
    src: "https://image.tmdb.org/t/p/w500/1pdfLvkbY9ohJlCjQH2CZjjYVvJ.jpg",
    className:
      "right-[-5%] top-[84%] h-[40vh] w-[40vw] max-w-[260px] rotate-[7deg] opacity-[0.12] sm:right-[8%]",
    sizes: "(max-width: 768px) 40vw, 260px",
  },
] as const;

/** Dimmed, page-tall poster field that scrolls with the landing page. */
export function LandingPosterBackdrop() {
  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-0 z-0 overflow-hidden">
      {PAGE_POSTERS.map((poster, index) => (
        <div
          key={`${poster.src}-${index}`}
          className={`absolute min-w-[160px] overflow-hidden rounded-[1.75rem] shadow-[0_30px_100px_rgba(0,0,0,0.8)] ${poster.className}`}
        >
          <Image
            src={poster.src}
            alt=""
            fill
            sizes={poster.sizes}
            className="object-cover brightness-[0.4] saturate-[0.55]"
            priority={index < 3}
          />
          <div className="absolute inset-0 bg-gradient-to-br from-canvas/30 via-transparent to-canvas/90" />
        </div>
      ))}
      <div className="absolute inset-0 bg-gradient-to-b from-canvas/55 via-canvas/35 to-canvas/70" />
      <div className="absolute inset-0 bg-gradient-to-r from-canvas/50 via-transparent to-canvas/45" />
    </div>
  );
}
