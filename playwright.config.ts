import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  workers: 1,
  use: { baseURL: "http://127.0.0.1:5173" },
  webServer: [
    {
      command: "npm --prefix web run dev",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command:
        "sam local start-api --template .aws-sam/build/template.yaml --host 127.0.0.1 --port 3001",
      url: "http://127.0.0.1:3001/health",
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
