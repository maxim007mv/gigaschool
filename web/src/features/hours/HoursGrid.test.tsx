/**
 * Тесты таблицы часов: рендер чисел, подсветка расхождений,
 * блокировка утверждения и клавиатурная навигация.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { emptyWorkload } from "../../entities/kit";
import { HoursGrid } from "./HoursGrid";
import type { LiveConstraints, LivePlan } from "./useLiveHours";

function planOneTopic(): LivePlan {
  return {
    modules: [
      {
        ref: "M1",
        title: "1. Первые шаги",
        plannedTotal: 2,
        topics: [
          { ref: "T1.1", title: "Знакомство", workload: emptyWorkload({ lecture: 1, practice: 1 }) },
        ],
      },
    ],
  };
}

function twoTopics(): LivePlan {
  return {
    modules: [
      {
        ref: "M1",
        title: "1. Первые шаги",
        plannedTotal: 4,
        topics: [
          { ref: "T1.1", title: "Знакомство", workload: emptyWorkload({ lecture: 1, practice: 1 }) },
          { ref: "T1.2", title: "Переменные", workload: emptyWorkload({ lecture: 1, practice: 1 }) },
        ],
      },
    ],
  };
}

describe("HoursGrid", () => {
  it("показывает часы тем и вычисленные итоги", () => {
    const constraints: LiveConstraints = { total: 2, finalAttHours: 0 };
    const { container } = render(
      <HoursGrid plan={planOneTopic()} constraints={constraints} onApprove={() => undefined} />,
    );

    const lecture = screen.getByLabelText("Лекции: тема T1.1 «Знакомство»");
    expect(lecture).toHaveValue("1");
    const practice = screen.getByLabelText("Практика: тема T1.1 «Знакомство»");
    expect(practice).toHaveValue("1");

    // Строка модуля и итог программы посчитаны: 2 ч (тема) + 0 ч (аттестация).
    expect(screen.getByText("Модуль M1 · 1. Первые шаги")).toBeInTheDocument();
    expect(screen.getByText(/Итог программы/)).toBeInTheDocument();
    expect(container.querySelector('[data-state="ok"]')).not.toBeNull();
    expect(container.querySelector('[data-state="error"]')).toBeNull();
  });

  it("подсвечивает расхождение и блокирует утверждение", () => {
    const constraints: LiveConstraints = { total: 20, finalAttHours: 0 };
    const onApprove = vi.fn();
    const { container } = render(
      <HoursGrid plan={planOneTopic()} constraints={constraints} onApprove={onApprove} />,
    );

    // Причина рядом с кнопкой (V-HRS-01).
    expect(screen.getByText("Сумма часов программы — 2 ч, а объём — 20 ч.")).toBeInTheDocument();
    const approve = screen.getByRole("button", { name: "Утвердить каркас" });
    expect(approve).toBeDisabled();
    fireEvent.click(approve);
    expect(onApprove).not.toHaveBeenCalled();

    // Красная подсветка ячейки итога — не только цветом (есть значок «!»).
    expect(container.querySelector('[data-state="error"]')).not.toBeNull();
    expect(container.querySelector('tr[data-issue="true"]')).not.toBeNull();
  });

  it("разрешает утверждение, когда часы сходятся", () => {
    const constraints: LiveConstraints = { total: 2, finalAttHours: 0 };
    const onApprove = vi.fn();
    render(<HoursGrid plan={planOneTopic()} constraints={constraints} onApprove={onApprove} />);

    const approve = screen.getByRole("button", { name: "Утвердить каркас" });
    expect(approve).toBeEnabled();
    fireEvent.click(approve);
    expect(onApprove).toHaveBeenCalledTimes(1);
  });

  it("передаёт новые часы ячейки без пересчёта на сервере", () => {
    const constraints: LiveConstraints = { total: 2, finalAttHours: 0 };
    const onCellChange = vi.fn();
    render(<HoursGrid plan={planOneTopic()} constraints={constraints} onCellChange={onCellChange} />);

    const lecture = screen.getByLabelText("Лекции: тема T1.1 «Знакомство»");
    fireEvent.change(lecture, { target: { value: "12" } });
    expect(onCellChange).toHaveBeenCalledWith("T1.1", "lecture", 12);
  });

  it("закрепляет ячейку замком", () => {
    const constraints: LiveConstraints = { total: 2, finalAttHours: 0 };
    const onToggleLock = vi.fn();
    render(<HoursGrid plan={planOneTopic()} constraints={constraints} onToggleLock={onToggleLock} />);

    const lock = screen.getByRole("button", { name: "Закрепить ячейку: Лекции, тема T1.1" });
    expect(lock).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(lock);
    expect(onToggleLock).toHaveBeenCalledWith("T1.1", "lecture");
  });

  it("навигация стрелками как в Excel: вниз по строкам", () => {
    const constraints: LiveConstraints = { total: 4, finalAttHours: 0 };
    render(<HoursGrid plan={twoTopics()} constraints={constraints} />);

    const first = screen.getByLabelText("Лекции: тема T1.1 «Знакомство»");
    const second = screen.getByLabelText("Лекции: тема T1.2 «Переменные»");
    first.focus();
    expect(first).toHaveFocus();
    fireEvent.keyDown(first, { key: "ArrowDown" });
    expect(second).toHaveFocus();
  });

  it("столбец «из них дистанционно» появляется при ДОТ", () => {
    const constraints: LiveConstraints = { total: 2, finalAttHours: 0, distanceMode: true };
    const plan = planOneTopic();
    plan.modules[0].topics[0].workload = emptyWorkload({ lecture: 1, practice: 1, distance: 1 });
    render(<HoursGrid plan={plan} constraints={constraints} />);
    expect(screen.getByText("из них дистанционно")).toBeInTheDocument();
  });
});
