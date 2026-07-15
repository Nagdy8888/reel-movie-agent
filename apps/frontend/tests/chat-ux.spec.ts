import { expect, test, type Page, type Route } from "@playwright/test";
import type { GraphData, SourceSummary } from "../lib/api";

/**
 * End-to-end UX walkthrough that drives the chat workspace the way a real user
 * would: sign in, ask a question, then ask a *second, different* question in the
 * same conversation. It guards the reported regression where the movie poster
 * and knowledge graph froze on the first answer instead of refreshing.
 */

const TINY_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
  "base64",
);

interface TurnFixture {
  answer: string;
  source: SourceSummary;
  graph: GraphData;
}

const HUNGER_GAMES: TurnFixture = {
  answer: "Jennifer Lawrence leads the cast as Katniss.",
  source: {
    id: "movie:hunger-games",
    title: "The Hunger Games",
    subtitle: "The world will be watching.",
    year: "2012",
    poster_url: "https://image.tmdb.org/t/p/w500/hunger_games.jpg",
    tags: ["Jennifer Lawrence"],
  },
  graph: {
    nodes: [
      { id: "movie:hunger-games", label: "The Hunger Games", type: "Movie" },
      { id: "person:jlaw", label: "Jennifer Lawrence", type: "Person" },
    ],
    links: [{ source: "person:jlaw", target: "movie:hunger-games", label: "Acted In" }],
  },
};

const SURVIVAL_SCIFI: TurnFixture = {
  answer: "Arrival and The Martian both explore survival against the odds.",
  source: {
    id: "movie:arrival",
    title: "Arrival",
    subtitle: "Why are they here?",
    year: "2016",
    poster_url: "https://image.tmdb.org/t/p/w500/arrival.jpg",
    tags: ["Amy Adams"],
  },
  graph: {
    nodes: [
      { id: "movie:arrival", label: "Arrival", type: "Movie" },
      { id: "movie:martian", label: "The Martian", type: "Movie" },
      { id: "genre:scifi", label: "Science Fiction", type: "Genre" },
    ],
    links: [
      { source: "movie:arrival", target: "genre:scifi", label: "In Genre" },
      { source: "movie:martian", target: "genre:scifi", label: "In Genre" },
    ],
  },
};

function sseBody(turn: TurnFixture): string {
  return [
    `event: meta\ndata: ${JSON.stringify({
      thread_id: "thread-ux",
      conversation_id: "conversation-ux",
    })}\n\n`,
    `event: sources\ndata: ${JSON.stringify({ sources: [turn.source] })}\n\n`,
    `event: graph\ndata: ${JSON.stringify(turn.graph)}\n\n`,
    `data: ${JSON.stringify({ token: turn.answer })}\n\n`,
    `event: done\ndata: {}\n\n`,
  ].join("");
}

async function authenticate(page: Page): Promise<void> {
  const now = Math.floor(Date.now() / 1000);
  const session = {
    access_token: "ux-token",
    token_type: "bearer",
    expires_in: 3600,
    expires_at: now + 3600,
    refresh_token: "ux-refresh",
    user: {
      id: "00000000-0000-4000-8000-000000000001",
      aud: "authenticated",
      role: "authenticated",
      email: "ux@example.com",
      app_metadata: {},
      user_metadata: { full_name: "UX Tester" },
      created_at: new Date().toISOString(),
    },
  };
  await page.context().addCookies([
    {
      name: "sb-bkhmqtcxoxtrydumgwfd-auth-token",
      value: `base64-${Buffer.from(JSON.stringify(session)).toString("base64url")}`,
      domain: "localhost",
      path: "/",
      expires: now + 3600,
      httpOnly: false,
      secure: false,
      sameSite: "Lax",
    },
  ]);
}

const CORS = { "Access-Control-Allow-Origin": "http://localhost:3000" };

async function setupRoutes(page: Page): Promise<void> {
  // Serve every optimized/remote poster request as a valid pixel so next/image
  // never falls back to the "broken poster" icon during the test.
  const servePng = (route: Route) =>
    route.fulfill({ status: 200, contentType: "image/png", body: TINY_PNG });
  await page.route(/\/_next\/image.*/, servePng);
  await page.route(/image\.tmdb\.org\/.*/, servePng);

  await page.route(/\/chats(?:\?.*)?$/, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", headers: CORS, json: [] }),
  );

  let turnIndex = 0;
  await page.route(/\/chat$/, (route) => {
    if (route.request().method() !== "POST") return route.continue();
    const turn = turnIndex === 0 ? HUNGER_GAMES : SURVIVAL_SCIFI;
    turnIndex += 1;
    return route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      headers: CORS,
      body: sseBody(turn),
    });
  });
}

test("poster and graph refresh when a second question is asked in the same chat", async ({
  page,
}) => {
  await authenticate(page);
  await setupRoutes(page);

  await page.goto("http://localhost:3000/chat");

  const input = page.getByPlaceholder("Ask about cast, genres, plots, or box office...");

  // Empty state before any question.
  await expect(
    page.getByText("Ask a movie question to build an answer network"),
  ).toBeVisible();

  // --- Turn 1: The Hunger Games ---
  await input.fill("Who starred in The Hunger Games?");
  await input.press("Enter");

  await expect(page.getByText(HUNGER_GAMES.answer)).toBeVisible();
  await expect(page.getByAltText("The Hunger Games poster")).toBeVisible();
  await expect(page.getByTestId("sigma-graph-ready")).toHaveText("2");
  await expect(page.getByText("2 nodes · 1 links")).toBeVisible();

  // --- Turn 2: a different question in the SAME conversation ---
  await input.fill("Sci-fi movies about survival");
  await input.press("Enter");

  await expect(page.getByText(SURVIVAL_SCIFI.answer)).toBeVisible();

  // The poster must swap to the new movie, not stay on the first answer.
  await expect(page.getByAltText("Arrival poster")).toBeVisible();
  await expect(page.getByAltText("The Hunger Games poster")).toHaveCount(0);

  // The knowledge graph must rebuild for the new answer.
  await expect(page.getByTestId("sigma-graph-ready")).toHaveText("3");
  await expect(page.getByText("3 nodes · 2 links")).toBeVisible();

  // Both user questions remain in the transcript (scoped to message bubbles,
  // since the same text also appears as suggestion chips).
  await expect(
    page.getByRole("paragraph").filter({ hasText: "Who starred in The Hunger Games?" }),
  ).toBeVisible();
  await expect(
    page.getByRole("paragraph").filter({ hasText: "Sci-fi movies about survival" }),
  ).toBeVisible();
});

test("shows a thinking indicator, then the grounded answer", async ({ page }) => {
  await authenticate(page);
  await setupRoutes(page);

  await page.goto("http://localhost:3000/chat");
  const input = page.getByPlaceholder("Ask about cast, genres, plots, or box office...");
  await input.fill("Who starred in The Hunger Games?");
  await input.press("Enter");

  await expect(page.getByText(HUNGER_GAMES.answer)).toBeVisible();
  await expect(page.getByText("Reel is searching the graph...")).toHaveCount(0);
});

test("does not hang the thinking indicator when a stream emits no answer token", async ({
  page,
}) => {
  await authenticate(page);
  // A fail-closed / empty-context reply can end the stream without any token
  // frame. The spinner must still stop.
  await page.route(/\/chats(?:\?.*)?$/, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", headers: CORS, json: [] }),
  );
  await page.route(/\/chat$/, (route) => {
    if (route.request().method() !== "POST") return route.continue();
    const body = [
      `event: meta\ndata: ${JSON.stringify({
        thread_id: "thread-empty",
        conversation_id: "conversation-empty",
      })}\n\n`,
      "event: done\ndata: {}\n\n",
    ].join("");
    return route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      headers: CORS,
      body,
    });
  });

  await page.goto("http://localhost:3000/chat");
  const input = page.getByPlaceholder("Ask about cast, genres, plots, or box office...");
  await input.fill("Tell me about a movie that does not exist");
  await input.press("Enter");

  await expect(page.getByText("Reel is searching the graph...")).toHaveCount(0);
  // The input is re-enabled so the user can try again.
  await expect(input).toBeEnabled();
});

test("starting a new discovery clears the previous answer's poster and graph", async ({
  page,
}) => {
  await authenticate(page);
  await setupRoutes(page);

  await page.goto("http://localhost:3000/chat");
  const input = page.getByPlaceholder("Ask about cast, genres, plots, or box office...");

  await input.fill("Who starred in The Hunger Games?");
  await input.press("Enter");
  await expect(page.getByAltText("The Hunger Games poster")).toBeVisible();

  await page.getByRole("button", { name: "New Discovery" }).click();

  await expect(page.getByAltText("The Hunger Games poster")).toHaveCount(0);
  await expect(
    page.getByText("Ask a movie question to build an answer network"),
  ).toBeVisible();
});
