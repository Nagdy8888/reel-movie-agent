import { expect, test, type Page } from "@playwright/test";
import type { GraphData } from "../lib/api";

const ANSWER_GRAPH: GraphData = {
  nodes: [
    { id: "movie:603", label: "The Matrix", type: "Movie" },
    { id: "person:6384", label: "Keanu Reeves", type: "Person" },
  ],
  links: [{ source: "person:6384", target: "movie:603", label: "Acted In" }],
};

const FULL_GRAPH: GraphData = {
  nodes: [
    ...ANSWER_GRAPH.nodes,
    { id: "genre:science%20fiction", label: "Science Fiction", type: "Genre" },
  ],
  links: [
    ...ANSWER_GRAPH.links,
    {
      source: "movie:603",
      target: "genre:science%20fiction",
      label: "In Genre",
    },
  ],
};

async function authenticate(page: Page): Promise<void> {
  const now = Math.floor(Date.now() / 1000);
  const session = {
    access_token: "focused-graph-token",
    token_type: "bearer",
    expires_in: 3600,
    expires_at: now + 3600,
    refresh_token: "focused-graph-refresh",
    user: {
      id: "00000000-0000-4000-8000-000000000001",
      aud: "authenticated",
      role: "authenticated",
      email: "focused@example.com",
      app_metadata: {},
      user_metadata: { full_name: "Focused Graph" },
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

test("answer graph is focused first and full graph loads on demand", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await authenticate(page);
  let fullGraphRequests = 0;
  await page.route(/\/graph$/, (route) => {
    fullGraphRequests += 1;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "Access-Control-Allow-Origin": "http://localhost:3000" },
      json: FULL_GRAPH,
    });
  });
  await page.route(/\/chats(?:\?.*)?$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "Access-Control-Allow-Origin": "http://localhost:3000" },
      json: [],
    }),
  );
  await page.route(/\/chat$/, (route) => {
    if (route.request().method() !== "POST") return route.continue();
    const source = {
      id: "movie:603",
      title: "The Matrix",
      subtitle: "Welcome to the Real World",
      year: "1999",
      poster_url: null,
      tags: ["Keanu Reeves"],
    };
    const body = [
      `event: meta\ndata: ${JSON.stringify({
        thread_id: "thread-1",
        conversation_id: "conversation-1",
      })}\n\n`,
      `event: sources\ndata: ${JSON.stringify({ sources: [source] })}\n\n`,
      `event: graph\ndata: ${JSON.stringify(ANSWER_GRAPH)}\n\n`,
      `data: ${JSON.stringify({ token: "Watch The Matrix." })}\n\n`,
      "event: done\ndata: {}\n\n",
    ].join("");
    return route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      headers: { "Access-Control-Allow-Origin": "http://localhost:3000" },
      body,
    });
  });

  await page.goto("http://localhost:3000/chat");
  await expect(page.getByText("Ask a movie question to build an answer network")).toBeVisible();
  expect(fullGraphRequests).toBe(0);

  await page
    .getByPlaceholder("Ask about cast, genres, plots, or box office...")
    .fill("Suggest a science fiction film");
  await page.getByPlaceholder("Ask about cast, genres, plots, or box office...").press("Enter");

  await expect(page.getByTestId("sigma-graph-ready")).toHaveText("2");
  await expect(page.getByText("2 nodes · 1 links")).toBeVisible();
  await page.getByRole("button", { name: "Show The Matrix in the answer network" }).click();
  await expect(page.getByText("1 visible relationship")).toBeVisible();

  await page.getByRole("button", { name: "Full network", exact: true }).click();
  await expect(page.getByTestId("sigma-graph-ready")).toHaveText("3");
  expect(fullGraphRequests).toBe(1);

  await page.getByRole("button", { name: "Keyword", exact: true }).click();
  await expect(page.getByTestId("sigma-graph-ready")).toHaveText("3");
  expect(fullGraphRequests).toBe(1);
});
