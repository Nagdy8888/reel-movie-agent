"use client";

import Image from "next/image";
import { useState } from "react";
import { MaterialIcon } from "./MaterialIcon";

/** A cited movie or person source card. */
export interface Source {
  id: string;
  title: string;
  subtitle?: string | null;
  year?: string | null;
  poster_url?: string | null;
  tags: string[];
}

export interface SourceCardProps {
  source: Source;
}

/** Render a single source card in the Sources panel. */
export function SourceCard({ source }: SourceCardProps) {
  const [posterFailed, setPosterFailed] = useState(false);
  const showPoster = Boolean(source.poster_url) && !posterFailed;

  return (
    <div className="bg-elevated border border-hairline rounded-lg overflow-hidden group hover:border-primary-container/50 transition-colors">
      <div className="h-36 relative w-full overflow-hidden bg-surface-container">
        {showPoster ? (
          <Image
            src={source.poster_url!}
            alt={`${source.title} poster`}
            fill
            className="object-cover object-top"
            sizes="340px"
            onError={() => setPosterFailed(true)}
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center bg-gradient-to-br from-surface-container-high to-surface-container">
            <MaterialIcon name="movie" className="text-primary-container/40 text-[40px]" />
          </div>
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-elevated via-elevated/20 to-transparent" />
        <div className="absolute bottom-sm left-sm right-sm flex justify-between items-end gap-sm">
          <span className="font-title-md text-[18px] text-on-surface text-glow leading-tight">
            {source.title}
          </span>
          {source.year && (
            <span className="font-body-sm text-[12px] text-on-surface-variant flex-shrink-0">
              {source.year}
            </span>
          )}
        </div>
      </div>
      {source.subtitle && (
        <p className="px-sm pt-sm font-body-sm text-body-sm text-on-surface-variant line-clamp-2">
          {source.subtitle}
        </p>
      )}
      <div className="p-sm flex flex-wrap gap-xs">
        {source.tags.map((tag) => (
          <span
            key={tag}
            className="px-2 py-0.5 rounded bg-surface-container border border-hairline text-primary-container font-label-caps text-[10px]"
          >
            {tag}
          </span>
        ))}
      </div>
    </div>
  );
}
