/** Unit tests for deterministic graph presentation helpers. */

import { describe, expect, it } from "vitest";
import type { GraphData } from "../api";
import {
  answerRootNodeIds,
  graphLinkKey,
  graphNodeById,
  visibleAnswerLinkKeys,
  visibleAnswerNodeIds,
} from "../graphView";

const ANSWER_GRAPH: GraphData = {
  nodes: [
    { id: "movie:1", label: "Movie", type: "Movie" },
    { id: "person:1", label: "Actor", type: "Person" },
  ],
  links: [{ source: "person:1", target: "movie:1", label: "ACTED_IN" }],
};

describe("graphView", () => {
  it("builds stable link keys and finds nodes", () => {
    expect(graphLinkKey(ANSWER_GRAPH.links[0])).toBe(
      "person:1->movie:1:ACTED_IN",
    );
    expect(graphNodeById(ANSWER_GRAPH, "person:1")?.label).toBe("Actor");
    expect(graphNodeById(ANSWER_GRAPH, "missing")).toBeNull();
  });

  it("returns answer entities visible in the rendered graph", () => {
    const rendered: GraphData = {
      nodes: [
        ...ANSWER_GRAPH.nodes,
        { id: "genre:1", label: "Drama", type: "Genre" },
      ],
      links: [
        ...ANSWER_GRAPH.links,
        { source: "movie:1", target: "genre:1", label: "IN_GENRE" },
      ],
    };

    expect(visibleAnswerNodeIds(ANSWER_GRAPH, rendered)).toEqual([
      "movie:1",
      "person:1",
    ]);
    expect(visibleAnswerLinkKeys(ANSWER_GRAPH, rendered)).toEqual([
      "person:1->movie:1:ACTED_IN",
    ]);
  });

  it("emphasizes movie roots and valid source IDs without duplicates", () => {
    expect(answerRootNodeIds(ANSWER_GRAPH, ["person:1", "movie:1", "missing"])).toEqual([
      "movie:1",
      "person:1",
    ]);
  });
});
