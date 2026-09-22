import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    globals: true,
    environment: "jsdom",
    restoreMocks: true,
    coverage: {
      provider: "v8",
      include: ["tests/static-notice-policy.js"],
      reportsDirectory: "coverage/unit",
      reporter: ["json", "text"],
      thresholds: {
        lines: 80,
        functions: 80,
        branches: 80,
        statements: 80
      }
    }
  }
});
