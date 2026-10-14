/**
 * Smoke-тест приложения: провайдеры, маршрутизация и список программ
 * реально монтируются, данные приходят из dev-моков (VITE_USE_MOCKS).
 */

import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "./providers";

describe("App (smoke)", () => {
  it("показывает список программ и навигацию", async () => {
    render(<App />);

    // Маршрут загружается асинхронно — ждём появления каркаса экрана.
    await waitFor(() => {
      expect(screen.getByText("КАРКАС")).toBeInTheDocument();
    });

    // Мок-данные: программа «Основы Python» с бейджем статуса.
    // Статус встречается и в бейдже, и в фильтре — проверяем наличие.
    await waitFor(() => {
      expect(screen.getByText("Основы Python")).toBeInTheDocument();
    });
    expect(screen.getAllByText("Каркас на проверке").length).toBeGreaterThan(0);
    expect(screen.getByText("Требуется ответ")).toBeInTheDocument();
  });
});
