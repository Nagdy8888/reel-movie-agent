/** Unit tests for validated JSON and resilient SSE parsing. */

import { afterEach, describe, expect, it, vi } from "vitest";
import { listChats, parseSseFrame, streamChat } from "../api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("parseSseFrame", () => {
  it("parses known event shapes", () => {
    expect(
      parseSseFrame(
        'event: meta\ndata: {"thread_id":"thread-1","conversation_id":"conversation-1"}',
      ),
    ).toEqual({
      type: "meta",
      thread_id: "thread-1",
      conversation_id: "conversation-1",
    });
    expect(parseSseFrame('data: {"token":"hello"}')).toEqual({
      type: "token",
      text: "hello",
    });
  });

  it("rejects malformed JSON and invalid payload shapes", () => {
    expect(parseSseFrame("data: {not-json")).toBeNull();
    expect(parseSseFrame('event: meta\ndata: {"thread_id":42}')).toBeNull();
    expect(parseSseFrame('event: graph\ndata: {"nodes":"invalid","links":[]}')).toBeNull();
  });
});

describe("streamChat", () => {
  it("skips a malformed frame and continues yielding later events", async () => {
    const body = [
      "data: {malformed}\n\n",
      'data: {"token":"still works"}\n\n',
      "event: done\ndata: {}\n\n",
    ].join("");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(body, {
          status: 200,
          headers: { "content-type": "text/event-stream" },
        }),
      ),
    );

    const events = [];
    for await (const event of streamChat("question", "token")) events.push(event);

    expect(events).toEqual([
      { type: "token", text: "still works" },
      { type: "done" },
    ]);
  });
});

describe("listChats", () => {
  it("rejects network responses that violate the conversation contract", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        Response.json([{ id: "missing-fields" }], { status: 200 }),
      ),
    );

    await expect(listChats("token")).rejects.toThrow(
      "listChats returned an invalid response",
    );
  });
});
