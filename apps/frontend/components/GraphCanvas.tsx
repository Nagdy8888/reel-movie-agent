"use client";

import dynamic from "next/dynamic";
import { useCallback, useMemo, useState } from "react";
import type { GraphData, SourceSummary } from "@/lib/api";
import {
  GRAPH_NODE_TYPES,
  answerRootNodeIds,
  graphNodeById,
  visibleAnswerLinkKeys,
  visibleAnswerNodeIds,
  type GraphMode,
  type GraphNodeType,
} from "@/lib/graphView";
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

const CATEGORY_STYLES: Record<GraphNodeType, string> = {
  Movie: "#9b8f7d",
  Person: "#4f4537",
  Genre: "#8f6fc0",
  Keyword: "#557f75",
};

type FullGraphStatus = "idle" | "loading" | "ready" | "error";

export interface GraphCanvasProps {
  answerGraph: GraphData;
  fullGraph: GraphData;
  fullGraphStatus: FullGraphStatus;
  mode: GraphMode;
  sources: SourceSummary[];
  selectedNodeId: string | null;
  onModeChange: (mode: GraphMode) => void;
  onRetryFullGraph: () => void;
  onSelectNode: (nodeId: string | null) => void;
}

interface SourcesDockProps {
  sources: SourceSummary[];
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
}

/** Floating source list that can focus its matching graph nodes. */
function SourcesDock({ sources, selectedNodeId, onSelectNode }: SourcesDockProps) {
  const [isOpen, setIsOpen] = useState(true);

  return (
    <section className="absolute top-md right-md z-30 w-[320px] max-w-[calc(100%-32px)] rounded-xl border border-hairline bg-canvas/90 backdrop-blur-xl shadow-[0_16px_48px_rgba(0,0,0,0.45)] overflow-hidden">
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        className="w-full px-md py-sm flex items-center justify-between text-left text-on-surface-variant hover:text-primary-container transition-colors"
        aria-expanded={isOpen}
      >
        <span className="font-title-md text-title-md">Sources ({sources.length})</span>
        <MaterialIcon name={isOpen ? "expand_less" : "expand_more"} size={20} />
      </button>
      {isOpen && (
        <div className="h-[220px] border-t border-hairline">
          <SourcesPanel
            sources={sources}
            selectedSourceId={selectedNodeId}
            onSelectSource={onSelectNode}
          />
        </div>
      )}
    </section>
  );
}

interface EmptyGraphStateProps {
  mode: GraphMode;
  status: FullGraphStatus;
  onRetry: () => void;
}

/** Explain why a graph is not visible and offer recovery when appropriate. */
function EmptyGraphState({ mode, status, onRetry }: EmptyGraphStateProps) {
  const loading = mode === "full" && (status === "idle" || status === "loading");
  return (
    <div className="h-full flex flex-col items-center justify-center text-center p-lg text-on-surface-variant">
      <MaterialIcon
        name="hub"
        className={`text-primary-container text-[56px] opacity-50 mb-md ${
          loading ? "animate-pulse" : ""
        }`}
      />
      <p className="font-title-md text-title-md text-on-surface mb-xs">
        {loading
          ? "Loading the full movie network"
          : mode === "answer"
            ? "Ask a movie question to build an answer network"
            : "The full network is unavailable"}
      </p>
      <p className="font-body-sm text-body-sm max-w-[360px]">
        {mode === "answer"
          ? "Only entities and relationships used for the answer will appear here."
          : loading
            ? "This larger explorer is loaded only when you request it."
            : "The focused answer network still works. You can retry the full explorer separately."}
      </p>
      {mode === "full" && status === "error" && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-md rounded-full border border-primary-container/60 px-md py-xs text-primary-container hover:bg-primary-container/10"
        >
          Retry full network
        </button>
      )}
    </div>
  );
}

/** WebGL graph canvas with a focused answer view and lazy full-network explorer. */
export function GraphCanvas({
  answerGraph,
  fullGraph,
  fullGraphStatus,
  mode,
  sources,
  selectedNodeId,
  onModeChange,
  onRetryFullGraph,
  onSelectNode,
}: GraphCanvasProps) {
  const [visibleTypes, setVisibleTypes] = useState<Set<GraphNodeType>>(
    () => new Set(GRAPH_NODE_TYPES),
  );
  const [resetNonce, setResetNonce] = useState(0);
  const graphData = mode === "answer" ? answerGraph : fullGraph;

  const emphasizedNodeIds = useMemo(
    () =>
      mode === "answer"
        ? answerRootNodeIds(answerGraph, sources.map((source) => source.id))
        : visibleAnswerNodeIds(answerGraph, graphData),
    [answerGraph, graphData, mode, sources],
  );
  const highlightedLinkKeys = useMemo(
    () => visibleAnswerLinkKeys(answerGraph, graphData),
    [answerGraph, graphData],
  );
  const selectedNode = useMemo(
    () => graphNodeById(graphData, selectedNodeId),
    [graphData, selectedNodeId],
  );
  const selectedRelationshipCount = useMemo(() => {
    if (!selectedNode) return 0;
    return graphData.links.filter(
      (link) => link.source === selectedNode.id || link.target === selectedNode.id,
    ).length;
  }, [graphData.links, selectedNode]);

  const toggleCategory = useCallback((category: GraphNodeType) => {
    setVisibleTypes((current) => {
      if (current.has(category) && current.size === 1) return current;
      const next = new Set(current);
      if (next.has(category)) next.delete(category);
      else next.add(category);
      return next;
    });
  }, []);

  return (
    <section className="flex flex-1 min-w-0 h-full flex-col bg-canvas relative overflow-hidden">
      <header className="relative flex-shrink-0 glass-panel z-20 px-md py-sm">
        <div className="flex flex-wrap items-center justify-between gap-sm">
          <div>
            <p className="font-label-caps text-label-caps text-primary-container">Knowledge Graph</p>
            <h2 className="font-headline-lg text-headline-lg text-on-surface">
              {mode === "answer" ? "Focused answer network" : "Full movie network"}
            </h2>
          </div>
          <div className="flex items-center gap-xs rounded-full border border-hairline bg-canvas/60 p-1">
            {(["answer", "full"] as const).map((viewMode) => (
              <button
                key={viewMode}
                type="button"
                onClick={() => onModeChange(viewMode)}
                aria-pressed={mode === viewMode}
                className={`rounded-full px-sm py-1 font-label-caps text-label-caps transition-colors ${
                  mode === viewMode
                    ? "bg-primary-container/20 text-primary-container"
                    : "text-on-surface-variant hover:text-on-surface"
                }`}
              >
                {viewMode === "answer" ? "Answer network" : "Full network"}
              </button>
            ))}
          </div>
        </div>
        <div className="mt-sm flex flex-wrap items-center gap-xs">
          {GRAPH_NODE_TYPES.map((category) => (
            <button
              key={category}
              type="button"
              onClick={() => toggleCategory(category)}
              aria-pressed={visibleTypes.has(category)}
              className={`inline-flex items-center gap-xs rounded-full border px-sm py-1 font-body-sm text-[11px] transition-colors ${
                visibleTypes.has(category)
                  ? "border-primary-container/50 text-on-surface"
                  : "border-hairline text-on-surface-variant opacity-55"
              }`}
            >
              <span
                className="inline-flex h-2.5 w-2.5 rounded-full"
                style={{ backgroundColor: CATEGORY_STYLES[category] }}
              />
              {category}
            </button>
          ))}
          <span className="ml-auto font-label-caps text-label-caps text-on-surface-variant">
            {graphData.nodes.length.toLocaleString()} nodes ·{" "}
            {graphData.links.length.toLocaleString()} links
          </span>
          <button
            type="button"
            onClick={() => setResetNonce((value) => value + 1)}
            className="rounded-full border border-hairline px-sm py-1 text-on-surface-variant hover:border-primary-container/60 hover:text-primary-container font-label-caps text-label-caps"
          >
            Reset view
          </button>
        </div>
      </header>

      <div className="relative min-h-0 flex-1">
        {graphData.nodes.length === 0 ? (
          <EmptyGraphState mode={mode} status={fullGraphStatus} onRetry={onRetryFullGraph} />
        ) : (
          <SigmaGraphRuntime
            graphData={graphData}
            mode={mode}
            emphasizedNodeIds={emphasizedNodeIds}
            highlightedLinkKeys={highlightedLinkKeys}
            selectedNodeId={selectedNodeId}
            visibleNodeTypes={[...visibleTypes]}
            resetNonce={resetNonce}
            onSelectNode={onSelectNode}
          />
        )}

        {sources.length > 0 && (
          <SourcesDock
            sources={sources}
            selectedNodeId={selectedNodeId}
            onSelectNode={onSelectNode}
          />
        )}

        {selectedNode && (
          <aside className="absolute bottom-md left-md z-30 max-w-[280px] rounded-xl border border-primary-container/35 bg-canvas/90 px-md py-sm backdrop-blur-xl shadow-lg">
            <div className="flex items-start justify-between gap-md">
              <div>
                <p className="font-label-caps text-label-caps text-primary-container">
                  {selectedNode.type}
                </p>
                <p className="font-title-md text-title-md text-on-surface">{selectedNode.label}</p>
                <p className="mt-xs font-body-sm text-body-sm text-on-surface-variant">
                  {selectedRelationshipCount} visible relationship
                  {selectedRelationshipCount === 1 ? "" : "s"}
                </p>
              </div>
              <button
                type="button"
                onClick={() => onSelectNode(null)}
                aria-label="Clear selected graph entity"
                className="text-on-surface-variant hover:text-on-surface"
              >
                <MaterialIcon name="close" size={18} />
              </button>
            </div>
          </aside>
        )}
      </div>
    </section>
  );
}
