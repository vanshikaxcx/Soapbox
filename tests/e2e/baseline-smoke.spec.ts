import { expect, test } from "@playwright/test";

test("redirects an unauthenticated visitor to Cognito sign-in", async ({ page }) => {
  // WP-03 replaced the static development baseline with the real Cognito
  // PKCE auth shell: an unauthenticated visit to any route (including /)
  // is redirected to the hosted UI, so there is no static heading to assert
  // on anymore. The redirect completes almost immediately, so assert on the
  // stable end state (arrival at the hosted UI) rather than the transient
  // "Redirecting..." notice, which toHaveURL's own polling can race and miss.
  await page.goto("/");

  await expect(page).toHaveURL(/amazoncognito\.com/);
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
