import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Конфигурация Vite и Vitest (Д3 §10: сборка по маршрутам, бюджеты frontend).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // В dev-режиме запросы /api/v1 уходят на локальный backend (Д4 §6.1).
    proxy: {
      "/api": {
        target: "http://localhost:8100",
        changeOrigin: true,
      },
    },
  },
  build: {
    target: "es2020",
    sourcemap: false,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
    restoreMocks: true,
  },
});
