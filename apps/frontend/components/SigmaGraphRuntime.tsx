"use client";

import {
  SigmaContainer,
  useCamera,
  useLoadGraph,
  useRegisterEvents,
  useSetSettings,
  useSigma,
} from "@react-sigma/core";
import { useWorkerLayoutForceAtlas2 } from "@react-sigma/layout-forceatlas2";
import { MultiDirectedGraph } from "graphology";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { GraphData, GraphLink, GraphNode } from "@/lib/api";
import "@react-sigma/core/lib/style.css";

const LAYOUT_DURATION_MS = 8_000;

export interface SigmaGraphRuntimeProps {
  graphData: GraphData;
  highlightedNodeIds: string[];
  highlightedLinkKeys: string[];
  resetNonce: number;
}

function stableHash(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function nodeStyle(node: GraphNode): { color: string; size: number } {
  if (node.type === "Movie") return { color: "#9b8f7d", size: 4.8 };
  if (node.type === "Person") return { color: "#4f4537", size: 2.7 };
  if (node.type === "Genre") return { color: "#8f6fc0", size: 4.2 };
  return { color: "#557f75", size: 2.2 };
}

function artifactLinkKey(link: GraphLink): string {
  return `${link.source}->${link.target}:${link.label}`;
}

function yieldToBrowser(): Promise<void> {
  return new Promise((resolve) => window.requestAnimationFrame(() => resolve()));
}

async function createGraph(data: GraphData): Promise<MultiDirectedGraph> {
  const graph = new MultiDirectedGraph();
  for (let index = 0; index < data.nodes.length; index += 1) {
    const node = data.nodes[index];
    const hash = stableHash(node.id);
    const angle = ((hash % 360_000) / 360_000) * Math.PI * 2;
    const radius = 0.25 + (((hash >>> 9) % 10_000) / 10_000) * 0.75;
    const style = nodeStyle(node);
    graph.addNode(node.id, {
      x: Math.cos(angle) * radius,
      y: Math.sin(angle) * radius,
      label: node.label,
      nodeType: node.type,
      color: style.color,
      size: style.size,
      zIndex: node.type === "Movie" ? 2 : 1,
    });
    if (index > 0 && index % 2_000 === 0) await yieldToBrowser();
  }
  for (let index = 0; index < data.links.length; index += 1) {
    const link = data.links[index];
    if (graph.hasNode(link.source) && graph.hasNode(link.target)) {
      graph.addDirectedEdgeWithKey(`edge:${index}`, link.source, link.target, {
        label: link.label,
        artifactKey: artifactLinkKey(link),
        color: "rgba(155,143,125,0.25)",
        size: 0.45,
        zIndex: 0,
      });
    }
    if (index > 0 && index % 5_000 === 0) await yieldToBrowser();
  }
  return graph;
}

interface LoadAndLayoutGraphProps {
  graphData: GraphData;
  onReady: () => void;
}

function LoadAndLayoutGraph({ graphData, onReady }: LoadAndLayoutGraphProps) {
  const loadGraph = useLoadGraph();
  const { start, stop } = useWorkerLayoutForceAtlas2({
    settings: {
      barnesHutOptimize: true,
      barnesHutTheta: 0.7,
      gravity: 0.8,
      linLogMode: true,
      scalingRatio: 6,
      slowDown: 8,
      strongGravityMode: false,
    },
  });

  useEffect(() => {
    let cancelled = false;
    let timeout: number | undefined;
    void createGraph(graphData).then((graph) => {
      if (cancelled) return;
      loadGraph(graph);
      start();
      onReady();
      timeout = window.setTimeout(() => stop(), LAYOUT_DURATION_MS);
    });
    return () => {
      cancelled = true;
      if (timeout !== undefined) window.clearTimeout(timeout);
      stop();
    };
  }, [graphData, loadGraph, onReady, start, stop]);

  return null;
}

interface HighlightControllerProps {
  highlightedNodeIds: string[];
  highlightedLinkKeys: string[];
  resetNonce: number;
}

function HighlightController({
  highlightedNodeIds,
  highlightedLinkKeys,
  resetNonce,
}: HighlightControllerProps) {
  const sigma = useSigma();
  const setSettings = useSetSettings();
  const registerEvents = useRegisterEvents();
  const { gotoNode, reset } = useCamera({ duration: 650 });
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const nodeIds = useMemo(() => new Set(highlightedNodeIds), [highlightedNodeIds]);
  const linkKeys = useMemo(() => new Set(highlightedLinkKeys), [highlightedLinkKeys]);
  const hasHighlight = nodeIds.size > 0 || linkKeys.size > 0;

  useEffect(() => {
    registerEvents({
      enterNode: ({ node }) => setHoveredNode(node),
      leaveNode: () => setHoveredNode(null),
    });
  }, [registerEvents]);

  useEffect(() => {
    setSettings({
      nodeReducer: (node, data) => {
        const reduced = { ...data };
        const isHighlighted = nodeIds.has(node);
        const isHovered = hoveredNode === node;
        if (isHighlighted || isHovered) {
          reduced.color = data.nodeType === "Movie" ? "#ffd185" : "#e8b457";
          reduced.size = Number(data.size) * 1.8;
          reduced.highlighted = true;
          reduced.forceLabel = true;
          reduced.zIndex = 10;
        } else if (hasHighlight) {
          reduced.color =
            data.nodeType === "Movie" ? "rgba(155,143,125,0.24)" : "rgba(79,69,55,0.25)";
          reduced.label = "";
        }
        return reduced;
      },
      edgeReducer: (_edge, data) => {
        const reduced = { ...data };
        const isHighlighted = linkKeys.has(String(data.artifactKey ?? ""));
        if (isHighlighted) {
          reduced.color = "rgba(255,209,133,0.92)";
          reduced.size = 2.2;
          reduced.zIndex = 8;
        } else if (hasHighlight) {
          reduced.color = "rgba(79,69,55,0.12)";
          reduced.size = 0.2;
        }
        return reduced;
      },
    });
  }, [hasHighlight, hoveredNode, linkKeys, nodeIds, setSettings]);

  useEffect(() => {
    const firstNode = highlightedNodeIds.find((nodeId) => sigma.getGraph().hasNode(nodeId));
    if (firstNode) void gotoNode(firstNode);
  }, [gotoNode, highlightedNodeIds, sigma]);

  useEffect(() => {
    if (resetNonce > 0) void reset();
  }, [reset, resetNonce]);

  return null;
}

/** Render a large graph through Sigma's WebGL pipeline and worker layout. */
export default function SigmaGraphRuntime({
  graphData,
  highlightedNodeIds,
  highlightedLinkKeys,
  resetNonce,
}: SigmaGraphRuntimeProps) {
  const [ready, setReady] = useState(false);
  const markReady = useCallback(() => setReady(true), []);

  useEffect(() => {
    queueMicrotask(() => setReady(false));
  }, [graphData]);

  return (
    <SigmaContainer
      className="h-full w-full"
      graph={MultiDirectedGraph}
      style={{ background: "#0E0E11" }}
      settings={{
        allowInvalidContainer: true,
        defaultNodeType: "circle",
        defaultEdgeType: "line",
        enableEdgeEvents: false,
        hideEdgesOnMove: true,
        hideLabelsOnMove: true,
        labelColor: { color: "#d3c4b1" },
        labelDensity: 0.08,
        labelGridCellSize: 180,
        labelRenderedSizeThreshold: 6,
        maxCameraRatio: 8,
        minCameraRatio: 0.03,
        renderEdgeLabels: false,
        stagePadding: 60,
        zIndex: true,
      }}
    >
      <LoadAndLayoutGraph graphData={graphData} onReady={markReady} />
      <HighlightController
        highlightedNodeIds={highlightedNodeIds}
        highlightedLinkKeys={highlightedLinkKeys}
        resetNonce={resetNonce}
      />
      <span data-testid="sigma-graph-ready" className="sr-only">
        {ready ? graphData.nodes.length : 0}
      </span>
    </SigmaContainer>
  );
}
