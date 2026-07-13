import type { GraphData, GraphLink, GraphNode } from "./api";

/** Graph presentation modes exposed by the workspace. */
export type GraphMode = "answer" | "full";

/** Node categories supported by the movie knowledge graph. */
export type GraphNodeType = GraphNode["type"];

/** All graph categories in toolbar display order. */
export const GRAPH_NODE_TYPES: GraphNodeType[] = ["Movie", "Person", "Genre", "Keyword"];

/** Stable identity for an artifact relationship. */
export function graphLinkKey(link: GraphLink): string {
  return `${link.source}->${link.target}:${link.label}`;
}

/** Return answer movie IDs that should receive primary visual emphasis. */
export function answerRootNodeIds(graph: GraphData, sourceIds: string[]): string[] {
  const graphNodeIds = new Set(graph.nodes.map((node) => node.id));
  const rootIds = new Set(
    graph.nodes.filter((node) => node.type === "Movie").map((node) => node.id),
  );
  for (const sourceId of sourceIds) {
    if (graphNodeIds.has(sourceId)) rootIds.add(sourceId);
  }
  return [...rootIds];
}

/** Return answer node IDs that also exist in the currently rendered graph. */
export function visibleAnswerNodeIds(answerGraph: GraphData, renderedGraph: GraphData): string[] {
  const renderedNodeIds = new Set(renderedGraph.nodes.map((node) => node.id));
  return answerGraph.nodes
    .map((node) => node.id)
    .filter((nodeId) => renderedNodeIds.has(nodeId));
}

/** Return answer relationship keys that also exist in the rendered graph. */
export function visibleAnswerLinkKeys(answerGraph: GraphData, renderedGraph: GraphData): string[] {
  const renderedLinkKeys = new Set(renderedGraph.links.map(graphLinkKey));
  return answerGraph.links
    .map(graphLinkKey)
    .filter((linkKey) => renderedLinkKeys.has(linkKey));
}

/** Find one node by stable ID without leaking graph lookup logic into UI components. */
export function graphNodeById(graph: GraphData, nodeId: string | null): GraphNode | null {
  if (!nodeId) return null;
  return graph.nodes.find((node) => node.id === nodeId) ?? null;
}
