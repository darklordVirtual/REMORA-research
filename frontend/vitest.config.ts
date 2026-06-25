import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    globals: false,
    include: ["src/**/*.test.ts"],
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      include: ["src/features/**/*"],
      exclude: ["src/**/*.test.ts", "src/**/*.d.ts"],
    },
  },
});
