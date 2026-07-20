"use client";

/** Focused-answer and lazy full-graph state for the workspace canvas. */

import { useCallback, useState } from "react";
import {
  getFullGraph,
  type GraphData,
  type SourceSummary,
} from "@/lib/api";
import type { FullGraphStatus, GraphMode } from "@/lib/graphView";

const EMPTY_GRAPH: GraphData = { nodes: [], links: [] };
const FULL_GRAPH_LOAD_ATTEMPTS = 3;
const FULL_GRAPH_RETRY_DELAY_MS = 1_000;

export interface UseAnswerGraphOptions {
  accessToken: string | null;
  onUnauthorized: () => void;
}

export interface AnswerGraphState {
  sources: SourceSummary[];
  graph: GraphData;
  fullGraph: GraphData;
  fullGraphStatus: FullGraphStatus;
  graphMode: GraphMode;
  selectedGraphNodeId: string | null;
  setSources: (sources: SourceSummary[]) => void;
  setAnswerGraph: (graph: GraphData) => void;
  resetAnswer: () => void;
  changeMode: (mode: GraphMode) => void;
  selectNode: (nodeId: string | null) => void;
  selectCitation: (nodeId: string) => void;
  retryFullGraph: () => void;
}

/** Own answer artifacts and retry the large full graph independently. */
export function useAnswerGraph({
  accessToken,
  onUnauthorized,
}: UseAnswerGraphOptions): AnswerGraphState {
  const [sources, setSources] = useState<SourceSummary[]>([]);
  const [graph, setGraph] = useState<GraphData>(EMPTY_GRAPH);
  const [fullGraph, setFullGraph] = useState<GraphData>(EMPTY_GRAPH);
  const [fullGraphStatus, setFullGraphStatus] = useState<FullGraphStatus>("idle");
  const [graphMode, setGraphMode] = useState<GraphMode>("answer");
  const [selectedGraphNodeId, setSelectedGraphNodeId] = useState<string | null>(null);

  const loadFullGraph = useCallback(async () => {
    if (!accessToken || fullGraphStatus === "loading" || fullGraphStatus === "ready") return;
    setFullGraphStatus("loading");

    for (let attempt = 0; attempt < FULL_GRAPH_LOAD_ATTEMPTS; attempt += 1) {
      try {
        const loadedGraph = await getFullGraph(accessToken);
        if (loadedGraph.nodes.length > 0) {
          setFullGraph(loadedGraph);
          setFullGraphStatus("ready");
          return;
        }
      } catch (caught) {
        if (caught instanceof Error && caught.message === "unauthorized") {
          onUnauthorized();
          return;
        }
      }

      if (attempt < FULL_GRAPH_LOAD_ATTEMPTS - 1) {
        await new Promise((resolve) => window.setTimeout(resolve, FULL_GRAPH_RETRY_DELAY_MS));
      }
    }
    setFullGraphStatus("error");
  }, [accessToken, fullGraphStatus, onUnauthorized]);

  const changeMode = useCallback(
    (mode: GraphMode) => {
      setGraphMode(mode);
      setSelectedGraphNodeId(null);
      if (mode === "full") void loadFullGraph();
    },
    [loadFullGraph],
  );

  const resetAnswer = useCallback(() => {
    setSources([]);
    setGraph(EMPTY_GRAPH);
    setGraphMode("answer");
    setSelectedGraphNodeId(null);
  }, []);

  const setAnswerGraph = useCallback((nextGraph: GraphData) => {
    setGraph(nextGraph);
    setGraphMode("answer");
    setSelectedGraphNodeId(null);
  }, []);

  const selectNode = useCallback((nodeId: string | null) => {
    setSelectedGraphNodeId(nodeId);
  }, []);

  const selectCitation = useCallback((nodeId: string) => {
    setGraphMode("answer");
    setSelectedGraphNodeId(nodeId);
  }, []);

  const retryFullGraph = useCallback(() => {
    setFullGraphStatus("idle");
    queueMicrotask(() => void loadFullGraph());
  }, [loadFullGraph]);

  return {
    sources,
    graph,
    fullGraph,
    fullGraphStatus,
    graphMode,
    selectedGraphNodeId,
    setSources,
    setAnswerGraph,
    resetAnswer,
    changeMode,
    selectNode,
    selectCitation,
    retryFullGraph,
  };
}
