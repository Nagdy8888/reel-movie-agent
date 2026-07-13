"use client";

import dynamic from "next/dynamic";
import { useCallback, useMemo, useState } from "react";
import type { GraphData, GraphLink, SourceSummary } from "@/lib/api";
import { MaterialIcon } from "./MaterialIcon";
import { SourcesPanel } from "./SourcesPanel";

const SigmaGraphRuntime = dynamic(() => import("./SigmaGraphRuntime"), {
  ssr: false,
  loading: () => (
    <div className="h-full flex items-center justify-center text-on-surface-variant">
      Initializing WebGL graph...
    </div>
  ),
});

type CategoryFilter = "all" | "Movie" | "Person" | "Genre" | "Keyword";

const CATEGORY_STYLES: Record<Exclude<CategoryFilter, "all">, string> = {
  Movie: "#9b8f7d",
  Person: "#4f4537",
  Genre: "#8f6fc0",
  Keyword: "#557f75",
};

export interface GraphCanvasProps {
  fullGraph: GraphData;
  highlight: GraphData;
  sources: SourceSummary[];
  loading: boolean;
}

function linkKey(link: GraphLink): string {
  return `${link.source}->${link.target}:${link.label}`;
}

function SourcesDock({ sources }: { sources: SourceSummary[] }) {
  const [isOpen, setIsOpen] = useState(true);

  return (
    <section className="absolute top-[80px] right-md z-30 w-[340px] max-w-[calc(100%-32px)] rounded-xl border border-hairline bg-canvas/85 backdrop-blur-xl shadow-[0_16px_48px_rgba(0,0,0,0.45)] overflow-hidden">
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        className="w-full px-md py-sm flex items-center justify-between text-left text-on-surface-variant hover:text-primary-container transition-colors"
      >
        <span className="font-title-md text-title-md">Sources ({sources.length})</span>
        <MaterialIcon name={isOpen ? "expand_less" : "expand_more"} size={20} />
      </button>
      {isOpen && (
        <div className="h-[220px] border-t border-hairline">
          <SourcesPanel sources={sources} />
        </div>
      )}
    </section>
  );
}

/** WebGL main graph canvas with answer-aware highlighting and worker layout. */
export function GraphCanvas({ fullGraph, highlight, sources, loading }: GraphCanvasProps) {
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>("all");
  const [resetNonce, setResetNonce] = useState(0);

  const graphData = useMemo<GraphData>(() => {
    const nodes =
      categoryFilter === "all"
        ? fullGraph.nodes
        : fullGraph.nodes.filter((node) => node.type === categoryFilter);
    const visibleNodeIds = new Set(nodes.map((node) => node.id));
    return {
      nodes,
      links: fullGraph.links.filter(
        (link) => visibleNodeIds.has(link.source) && visibleNodeIds.has(link.target),
      ),
    };
  }, [categoryFilter, fullGraph]);

  const selectedMovieIds = useMemo(() => {
    const ids = new Set(sources.map((source) => source.id));
    for (const node of highlight.nodes) {
      if (node.type === "Movie") ids.add(node.id);
    }
    return ids;
  }, [highlight.nodes, sources]);

  const highlightedNodeIds = useMemo(() => {
    const ids = new Set(highlight.nodes.map((node) => node.id));
    for (const movieId of selectedMovieIds) ids.add(movieId);
    for (const link of graphData.links) {
      if (selectedMovieIds.has(link.source) || selectedMovieIds.has(link.target)) {
        ids.add(link.source);
        ids.add(link.target);
      }
    }
    return [...ids].filter((id) => graphData.nodes.some((node) => node.id === id));
  }, [graphData.links, graphData.nodes, highlight.nodes, selectedMovieIds]);

  const highlightedLinkKeys = useMemo(() => {
    const keys = new Set(highlight.links.map(linkKey));
    for (const link of graphData.links) {
      if (selectedMovieIds.has(link.source) || selectedMovieIds.has(link.target)) {
        keys.add(linkKey(link));
      }
    }
    return [...keys];
  }, [graphData.links, highlight.links, selectedMovieIds]);

  const hasHighlight = highlightedNodeIds.length > 0 || highlightedLinkKeys.length > 0;

  const toggleCategoryFilter = useCallback(
    (filter: Exclude<CategoryFilter, "all">) => {
      setCategoryFilter((current) => (current === filter ? "all" : filter));
    },
    [],
  );

  return (
    <section className="flex-1 min-w-0 h-full bg-canvas relative overflow-hidden">
      <div className="absolute top-0 left-0 right-0 h-[64px] glass-panel z-20 flex items-center justify-between px-lg">
        <div>
          <p className="font-label-caps text-label-caps text-primary-container">Knowledge Graph</p>
          <h2 className="font-headline-lg text-headline-lg text-on-surface">
            {hasHighlight ? "Answer network highlighted" : "Full movie network"}
          </h2>
        </div>
        <div className="flex items-center gap-md">
          <div className="hidden xl:flex items-center gap-xs font-body-sm text-body-sm text-on-surface-variant">
            {(Object.keys(CATEGORY_STYLES) as Array<Exclude<CategoryFilter, "all">>).map(
              (category) => (
                <button
                  key={category}
                  type="button"
                  onClick={() => toggleCategoryFilter(category)}
                  aria-pressed={categoryFilter === category}
                  className={`inline-flex items-center gap-xs rounded-full border px-sm py-1 transition-colors ${
                    categoryFilter === category
                      ? "border-primary-container bg-primary-container/15 text-primary-container"
                      : "border-hairline hover:border-primary-container/60 hover:text-primary-container"
                  }`}
                >
                  <span
                    className="inline-flex h-3 w-3 rounded-full"
                    style={{ backgroundColor: CATEGORY_STYLES[category] }}
                  />
                  {category}
                </button>
              ),
            )}
          </div>
          <span className="hidden 2xl:inline font-label-caps text-label-caps text-on-surface-variant">
            {graphData.nodes.length.toLocaleString()} nodes
          </span>
          <button
            type="button"
            onClick={() => setResetNonce((value) => value + 1)}
            className="px-sm py-1 rounded-full border border-hairline text-on-surface-variant hover:text-primary-container hover:border-primary-container/60 transition-colors font-label-caps text-label-caps"
          >
            Reset view
          </button>
        </div>
      </div>
      <div className="absolute inset-0 pt-[64px]">
        {loading ? (
          <div className="h-full flex flex-col items-center justify-center text-on-surface-variant">
            <MaterialIcon
              name="hub"
              className="text-primary-container text-[56px] opacity-60 animate-pulse mb-md"
            />
            <p className="font-body-sm text-body-sm">Loading the movie graph...</p>
          </div>
        ) : graphData.nodes.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center p-lg text-on-surface-variant">
            <MaterialIcon
              name="hub"
              className="text-primary-container text-[56px] opacity-50 mb-md"
            />
            <p className="font-body-sm text-body-sm max-w-[320px]">
              The full graph is unavailable right now. Chat can still continue, and highlights
              will appear when graph data returns.
            </p>
          </div>
        ) : (
          <SigmaGraphRuntime
            graphData={graphData}
            highlightedNodeIds={highlightedNodeIds}
            highlightedLinkKeys={highlightedLinkKeys}
            resetNonce={resetNonce}
          />
        )}
      </div>
      <SourcesDock sources={sources} />
    </section>
  );
}
