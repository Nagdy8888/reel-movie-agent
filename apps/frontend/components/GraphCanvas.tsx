"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState, type ComponentType, type MutableRefObject } from "react";
import type { ForceGraphMethods, LinkObject, NodeObject } from "react-force-graph-2d";
import type { GraphData, GraphLink, GraphNode, SourceSummary } from "@/lib/api";
import { MaterialIcon } from "./MaterialIcon";
import { SourcesPanel } from "./SourcesPanel";

type CanvasNode = NodeObject<GraphNode & { __bckgDimensions?: [number, number] }>;
type CanvasLink = LinkObject<GraphNode, GraphLink> & GraphLink;
type GraphRef = ForceGraphMethods<CanvasNode, CanvasLink>;
type LinkEndpoint = string | number | { id?: string | number } | null | undefined;

interface ForceGraphRuntimeProps {
  ref?: MutableRefObject<GraphRef | undefined>;
  graphData: { nodes: CanvasNode[]; links: CanvasLink[] };
  nodeId: string;
  linkSource: string;
  linkTarget: string;
  width: number;
  height: number;
  backgroundColor: string;
  minZoom: number;
  maxZoom: number;
  cooldownTicks: number;
  d3AlphaDecay: number;
  d3VelocityDecay: number;
  enableNodeDrag: boolean;
  nodeLabel: (node: CanvasNode) => string;
  linkLabel: (link: CanvasLink) => string;
  linkWidth: (link: CanvasLink) => number;
  linkColor: (link: CanvasLink) => string;
  linkDirectionalArrowLength: (link: CanvasLink) => number;
  linkDirectionalArrowColor: (link: CanvasLink) => string;
  linkDirectionalParticles: (link: CanvasLink) => number;
  linkDirectionalParticleColor: (link: CanvasLink) => string;
  linkDirectionalParticleWidth: (link: CanvasLink) => number;
  nodeCanvasObject: (node: CanvasNode, ctx: CanvasRenderingContext2D, globalScale: number) => void;
  nodePointerAreaPaint: (
    node: CanvasNode,
    color: string,
    ctx: CanvasRenderingContext2D,
    globalScale: number,
  ) => void;
}

const ForceGraph2D = dynamic<ForceGraphRuntimeProps>(
  async () => (await import("react-force-graph-2d")).default as ComponentType<ForceGraphRuntimeProps>,
  { ssr: false },
);

export interface GraphCanvasProps {
  fullGraph: GraphData;
  highlight: GraphData;
  sources: SourceSummary[];
  loading: boolean;
}

function endpointId(endpoint: LinkEndpoint): string {
  if (typeof endpoint === "string" || typeof endpoint === "number") return String(endpoint);
  return String(endpoint?.id ?? "");
}

function linkKey(link: GraphLink | CanvasLink): string {
  return `${endpointId(link.source as LinkEndpoint)}->${endpointId(link.target as LinkEndpoint)}:${link.label}`;
}

function nodeColor(node: CanvasNode, isHighlighted: boolean, hasHighlight: boolean): string {
  if (isHighlighted) return node.type === "Movie" ? "#ffd185" : "#e8b457";
  if (hasHighlight) return node.type === "Movie" ? "rgba(155,143,125,0.28)" : "rgba(79,69,55,0.35)";
  return node.type === "Movie" ? "#9b8f7d" : "#4f4537";
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

/** Force-directed main graph canvas with answer-aware highlighting. */
export function GraphCanvas({ fullGraph, highlight, sources, loading }: GraphCanvasProps) {
  const graphRef = useRef<GraphRef | undefined>(undefined);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  const graphData = useMemo(
    () => ({
      nodes: fullGraph.nodes.map((node) => ({ ...node })),
      links: fullGraph.links.map((link) => ({ ...link })),
    }),
    [fullGraph],
  );

  const highlightedNodeIds = useMemo(
    () => new Set(highlight.nodes.map((node) => node.id)),
    [highlight.nodes],
  );
  const highlightedLinkKeys = useMemo(
    () => new Set(highlight.links.map((link) => linkKey(link))),
    [highlight.links],
  );
  const hasHighlight = highlightedNodeIds.size > 0 || highlightedLinkKeys.size > 0;
  const highlightKey = useMemo(
    () => [...highlightedNodeIds].sort().join("|"),
    [highlightedNodeIds],
  );

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const observer = new ResizeObserver(([entry]) => {
      const rect = entry.contentRect;
      setSize({ width: Math.floor(rect.width), height: Math.floor(rect.height) });
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (size.width <= 0 || size.height <= 0 || graphData.nodes.length === 0) return;
    const timer = window.setTimeout(() => {
      const filter =
        highlightedNodeIds.size > 0
          ? (node: CanvasNode) => highlightedNodeIds.has(String(node.id))
          : undefined;
      graphRef.current?.zoomToFit(650, highlightedNodeIds.size > 0 ? 120 : 70, filter);
    }, 350);
    return () => window.clearTimeout(timer);
  }, [graphData.nodes.length, highlightKey, highlightedNodeIds, size.height, size.width]);

  const resetView = useCallback(() => {
    graphRef.current?.zoomToFit(500, 70);
  }, []);

  const drawNode = useCallback(
    (node: CanvasNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const id = String(node.id ?? "");
      const isHighlighted = highlightedNodeIds.has(id);
      const fill = nodeColor(node, isHighlighted, hasHighlight);
      const radius = isHighlighted ? (node.type === "Movie" ? 9 : 7) : node.type === "Movie" ? 6 : 4.5;
      const x = node.x ?? 0;
      const y = node.y ?? 0;

      if (isHighlighted) {
        ctx.beginPath();
        ctx.arc(x, y, radius + 6, 0, 2 * Math.PI);
        ctx.fillStyle = "rgba(232, 180, 87, 0.16)";
        ctx.fill();
      }

      ctx.beginPath();
      ctx.arc(x, y, radius, 0, 2 * Math.PI);
      ctx.fillStyle = fill;
      ctx.fill();
      ctx.strokeStyle = isHighlighted ? "#ffd185" : "rgba(211,196,177,0.35)";
      ctx.lineWidth = isHighlighted ? 1.6 : 0.8;
      ctx.stroke();

      const shouldShowLabel = isHighlighted || !hasHighlight || globalScale > 1.05;
      if (!shouldShowLabel) {
        node.__bckgDimensions = [radius * 2, radius * 2];
        return;
      }

      const label = node.label.length > 24 ? `${node.label.slice(0, 23)}...` : node.label;
      const fontSize = (isHighlighted ? 13 : 10) / globalScale;
      ctx.font = `${fontSize}px DM Sans, sans-serif`;
      const textWidth = ctx.measureText(label).width;
      const labelWidth = textWidth + fontSize * 0.8;
      const labelHeight = fontSize * 1.6;
      const labelY = y + radius + labelHeight * 0.65;

      ctx.fillStyle = isHighlighted ? "rgba(28,28,34,0.92)" : "rgba(28,28,34,0.72)";
      ctx.fillRect(x - labelWidth / 2, labelY - labelHeight / 2, labelWidth, labelHeight);
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillStyle = isHighlighted ? "#ffd185" : hasHighlight ? "rgba(211,196,177,0.48)" : "#d3c4b1";
      ctx.fillText(label, x, labelY);
      node.__bckgDimensions = [Math.max(labelWidth, radius * 2), radius * 2 + labelHeight];
    },
    [hasHighlight, highlightedNodeIds],
  );

  const paintNodePointer = useCallback(
    (node: CanvasNode, color: string, ctx: CanvasRenderingContext2D) => {
      const x = node.x ?? 0;
      const y = node.y ?? 0;
      const [width, height] = node.__bckgDimensions ?? [24, 24];
      ctx.fillStyle = color;
      ctx.fillRect(x - width / 2, y - 12, width, height + 16);
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
          <div className="hidden lg:flex items-center gap-sm font-body-sm text-body-sm text-on-surface-variant">
            <span className="inline-flex h-3 w-3 rounded-full bg-primary" />
            Movie
            <span className="inline-flex h-3 w-3 rounded-full bg-primary-container" />
            Person
          </div>
          <button
            type="button"
            onClick={resetView}
            className="px-sm py-1 rounded-full border border-hairline text-on-surface-variant hover:text-primary-container hover:border-primary-container/60 transition-colors font-label-caps text-label-caps"
          >
            Reset view
          </button>
        </div>
      </div>
      <div ref={containerRef} className="absolute inset-0 pt-[64px]">
        {loading ? (
          <div className="h-full flex flex-col items-center justify-center text-on-surface-variant">
            <MaterialIcon name="hub" className="text-primary-container text-[56px] opacity-60 animate-pulse mb-md" />
            <p className="font-body-sm text-body-sm">Loading the movie graph...</p>
          </div>
        ) : graphData.nodes.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center p-lg text-on-surface-variant">
            <MaterialIcon name="hub" className="text-primary-container text-[56px] opacity-50 mb-md" />
            <p className="font-body-sm text-body-sm max-w-[320px]">
              The full graph is unavailable right now. Chat can still continue, and highlights will appear when graph data returns.
            </p>
          </div>
        ) : size.width > 0 && size.height > 0 ? (
          <ForceGraph2D
            ref={graphRef}
            graphData={graphData}
            nodeId="id"
            linkSource="source"
            linkTarget="target"
            width={size.width}
            height={size.height}
            backgroundColor="#0E0E11"
            minZoom={0.08}
            maxZoom={8}
            cooldownTicks={120}
            d3AlphaDecay={0.018}
            d3VelocityDecay={0.28}
            enableNodeDrag
            nodeLabel={(node) => `${node.type}: ${node.label}`}
            linkLabel={(link) => link.label}
            linkWidth={(link) => (highlightedLinkKeys.has(linkKey(link)) ? 2.2 : hasHighlight ? 0.35 : 0.8)}
            linkColor={(link) =>
              highlightedLinkKeys.has(linkKey(link))
                ? "rgba(255,209,133,0.92)"
                : hasHighlight
                  ? "rgba(79,69,55,0.22)"
                  : "rgba(155,143,125,0.42)"
            }
            linkDirectionalArrowLength={(link) => (highlightedLinkKeys.has(linkKey(link)) ? 4 : 0)}
            linkDirectionalArrowColor={() => "rgba(255,209,133,0.8)"}
            linkDirectionalParticles={(link) => (highlightedLinkKeys.has(linkKey(link)) ? 2 : 0)}
            linkDirectionalParticleColor={() => "#ffd185"}
            linkDirectionalParticleWidth={() => 2}
            nodeCanvasObject={drawNode}
            nodePointerAreaPaint={paintNodePointer}
          />
        ) : null}
      </div>
      <SourcesDock sources={sources} />
    </section>
  );
}
