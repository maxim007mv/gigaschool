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

    // Мок-данные: программа в статусе framework_review и кнопка следующего шага.
    await waitFor(() => {
      expect(screen.getByText(/Искусственный интеллект для учителя/)).toBeInTheDocument();
    });
    expect(screen.getByRole("link", { name: "Проверить часы" })).toBeInTheDocument();
  });
});
