/** Unit tests for complete sidebar recency grouping. */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ConversationSummary } from "../api";
import { groupChatsByRecency } from "../groupChats";

/** Build a minimal conversation at one local timestamp. */
function conversation(id: string, updatedAt: Date): ConversationSummary {
  return {
    id,
    thread_id: `thread-${id}`,
    title: id,
    created_at: updatedAt.toISOString(),
    updated_at: updatedAt.toISOString(),
  };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date(2026, 6, 20, 12));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("groupChatsByRecency", () => {
  it("keeps today, recent, and older conversations visible", () => {
    const grouped = groupChatsByRecency([
      conversation("today", new Date(2026, 6, 20, 9)),
      conversation("recent", new Date(2026, 6, 17, 9)),
      conversation("older", new Date(2026, 5, 1, 9)),
    ]);

    expect(grouped.today.map(({ id }) => id)).toEqual(["today"]);
    expect(grouped.previous7Days.map(({ id }) => id)).toEqual(["recent"]);
    expect(grouped.older.map(({ id }) => id)).toEqual(["older"]);
  });
});
