import { expect, test } from "@playwright/test";

test("renders the static development baseline", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "ProofPath" })).toBeVisible();
  await expect(page.getByText("Development baseline")).toBeVisible();
});

test("returns the health envelope through the API", async ({ request }) => {
  const response = await request.get("http://127.0.0.1:3001/health");

  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toContain("application/json");
  const body: unknown = await response.json();
  expect(body).toMatchObject({ data: { status: "ok" } });
  expect(response.headers()["x-request-id"]).toBe(
    (body as { request_id: string }).request_id,
  );
});
