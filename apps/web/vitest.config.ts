import { defineConfig } from "vitest/config";
import path from "path";

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
      // ../../ — this file lives in apps/web, and packages/ is at the repo root.
      "@outreach-os/shared-types": path.resolve(__dirname, "../../packages/shared-types/src/index.ts"),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
  },
});
