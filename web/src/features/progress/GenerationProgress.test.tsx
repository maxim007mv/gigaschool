/**
 * Блок ожидания сборки: прогресс по шагам и понятный текст ошибки.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { GenerationProgress } from "./GenerationProgress";

describe("GenerationProgress", () => {
  it("показывает текущий шаг и числовой прогресс", () => {
    render(
      <GenerationProgress
        title="Собираем каркас"
        description="Формируем модули и темы"
        estimate="Обычно до 3 минут"
        progress={{
          job_id: "job-1",
          step: "S07",
          label: "Строим модули и темы",
          done: 2,
          total: 5,
        }}
      />,
    );

    expect(screen.getByText("Строим модули и темы")).toBeInTheDocument();
    expect(screen.getByText("2 из 5")).toBeInTheDocument();
    expect(screen.getByText("осталось шагов: 3")).toBeInTheDocument();
    expect(screen.getByText("Обычно до 3 минут")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Строим модули и темы" })).toHaveAttribute(
      "aria-valuenow",
      "2",
    );
  });

  it("при ошибке объясняет, что делать, и даёт повторить", () => {
    const onRetry = vi.fn();
    render(
      <GenerationProgress
        title="Собираем каркас"
        description="Формируем модули и темы"
        estimate="Обычно до 3 минут"
        failure={{ code: "LLM_UNAVAILABLE", detail: "Сервис сборки временно недоступен" }}
        failureHint="Проверьте параметры программы и повторите сборку."
        onRetry={onRetry}
        retryLabel="Повторить сборку каркаса"
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Сервис сборки временно недоступен");
    expect(screen.getByText("Проверьте параметры программы и повторите сборку.")).toBeInTheDocument();
    expect(screen.getByText(/LLM_UNAVAILABLE/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Повторить сборку каркаса" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
