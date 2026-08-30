import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    globals: true,
    environment: "jsdom",
    restoreMocks: true,
    coverage: {
      provider: "v8",
      include: ["app/scripts/**/*.js"],
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
