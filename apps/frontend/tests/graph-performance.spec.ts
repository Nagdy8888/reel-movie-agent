import { expect, test } from "@playwright/test";
import { gunzipSync } from "node:zlib";
import { readFileSync } from "node:fs";
import path from "node:path";
import type { GraphData } from "../lib/api";

interface BundlePerson {
  tmdbId: number;
  name: string;
}

interface BundleMovie {
  tmdbId: number;
  title: string;
  genres: string[];
  keywords: string[];
  cast: BundlePerson[];
  directors: BundlePerson[];
  writers: BundlePerson[];
  producers: BundlePerson[];
}

interface MovieBundle {
  movies: BundleMovie[];
}

function namedId(type: "Genre" | "Keyword", name: string): string {
  return `${type.toLowerCase()}:${encodeURIComponent(name.toLocaleLowerCase())}`;
}

function loadCompleteGraph(): GraphData {
  const bundlePath = path.resolve(
    process.cwd(),
    "../agents/src/agents/data/movies_subset.json.gz",
  );
  const bundle = JSON.parse(gunzipSync(readFileSync(bundlePath)).toString("utf8")) as MovieBundle;
  const nodes = new Map<string, GraphData["nodes"][number]>();
  const links: GraphData["links"] = [];

  for (const movie of bundle.movies) {
    const movieId = `movie:${movie.tmdbId}`;
    nodes.set(movieId, { id: movieId, label: movie.title, type: "Movie" });
    for (const [field, label] of [
      ["cast", "Acted In"],
      ["directors", "Directed"],
      ["writers", "Wrote"],
      ["producers", "Produced"],
    ] as const) {
      for (const person of movie[field]) {
        const personId = `person:${person.tmdbId}`;
        nodes.set(personId, { id: personId, label: person.name, type: "Person" });
        links.push({ source: personId, target: movieId, label });
      }
    }
    for (const genre of movie.genres) {
      const genreId = namedId("Genre", genre);
      nodes.set(genreId, { id: genreId, label: genre, type: "Genre" });
      links.push({ source: movieId, target: genreId, label: "In Genre" });
    }
    for (const keyword of movie.keywords) {
      const keywordId = namedId("Keyword", keyword);
      nodes.set(keywordId, { id: keywordId, label: keyword, type: "Keyword" });
      links.push({ source: movieId, target: keywordId, label: "Has Keyword" });
    }
  }
  return { nodes: [...nodes.values()], links };
}

test("complete graph stays responsive under WebGL worker layout", async ({ page }) => {
  const graph = loadCompleteGraph();
  expect(graph.nodes).toHaveLength(48_734);
  expect(graph.links).toHaveLength(136_709);

  const now = Math.floor(Date.now() / 1000);
  const user = {
    id: "00000000-0000-4000-8000-000000000001",
    aud: "authenticated",
    role: "authenticated",
    email: "benchmark@example.com",
    app_metadata: {},
    user_metadata: { full_name: "Graph Benchmark" },
    created_at: new Date().toISOString(),
  };
  const session = {
    access_token: "benchmark-token",
    token_type: "bearer",
    expires_in: 3600,
    expires_at: now + 3600,
    refresh_token: "benchmark-refresh",
    user,
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
  await page.route(/\/graph$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "Access-Control-Allow-Origin": "http://localhost:3000" },
      json: graph,
    }),
  );
  await page.route(/\/chats(?:\?.*)?$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "Access-Control-Allow-Origin": "http://localhost:3000" },
      json: [],
    }),
  );

  const started = Date.now();
  await page.goto("http://localhost:3000/chat");
  await expect(page.getByText("Ask a movie question to build an answer network")).toBeVisible();
  await page.getByRole("button", { name: "Full network", exact: true }).click();
  await expect(page.getByText(/48,734 nodes/)).toBeAttached({ timeout: 30_000 });
  await expect(page.locator("canvas").first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("sigma-graph-ready")).toHaveText("48734", {
    timeout: 30_000,
  });
  const firstRenderMs = Date.now() - started;

  const timerDelayMs = await page.evaluate(
    () =>
      new Promise<number>((resolve) => {
        const before = performance.now();
        window.setTimeout(() => resolve(performance.now() - before), 100);
      }),
  );
  expect(firstRenderMs).toBeLessThan(30_000);
  expect(timerDelayMs).toBeLessThan(1_000);

  await page.locator("canvas.sigma-mouse").hover();
  await page.mouse.wheel(0, -400);
  const filterStarted = Date.now();
  await page.getByRole("button", { name: "Keyword", exact: true }).click();
  await expect(page.getByTestId("sigma-graph-ready")).toHaveText("48734");
  expect(Date.now() - filterStarted).toBeLessThan(2_000);
  await page.getByRole("button", { name: "Reset view" }).click();

  console.log(
    JSON.stringify({
      nodes: graph.nodes.length,
      links: graph.links.length,
      firstRenderMs,
      timerDelayMs: Math.round(timerDelayMs),
    }),
  );
});
