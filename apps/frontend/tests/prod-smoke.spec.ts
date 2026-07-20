import { expect, test } from "@playwright/test";

const FRONTEND = "https://reel-frontend-six.vercel.app";
const EMAIL = "reel-smoke-test@example.com";
const PASSWORD = "ReelTestPass123!";

test.describe.configure({ mode: "serial" });

test("production login and two-turn chat refresh poster/graph", async ({ page }) => {
  test.setTimeout(180_000);

  await page.goto(`${FRONTEND}/login`);
  await page.getByPlaceholder("cinephile@example.com").fill(EMAIL);
  await page.getByPlaceholder("••••••••").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(`${FRONTEND}/chat`, { timeout: 30_000 });

  const input = page.getByPlaceholder("Ask about cast, genres, plots, or box office...");
  await expect(input).toBeEnabled({ timeout: 15_000 });

  await input.fill("Who starred in The Hunger Games?");
  await input.press("Enter");

  await expect(page.getByText("Reel is searching the graph...")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText("Reel is searching the graph...")).toHaveCount(0, { timeout: 120_000 });
  await expect(page.getByAltText(/The Hunger Games poster/i)).toBeVisible({ timeout: 30_000 });
  const nodesAfterFirst = await page.getByText(/\d+ nodes · \d+ links/).innerText();

  await input.fill("Sci-fi movies about survival");
  await input.press("Enter");

  await expect(page.getByText("Reel is searching the graph...")).toHaveCount(0, { timeout: 120_000 });
  await expect(page.getByAltText(/The Hunger Games poster/i)).toHaveCount(0, { timeout: 30_000 });
  const nodesAfterSecond = await page.getByText(/\d+ nodes · \d+ links/).innerText();
  expect(nodesAfterSecond).not.toEqual(nodesAfterFirst);
});
