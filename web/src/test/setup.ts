import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

// jsdom не реализует window.scrollTo; роутер вызывает его при восстановлении
// прокрутки — заглушка убирает шум «Not implemented» из вывода тестов.
window.scrollTo = () => undefined;

// Общая настройка тестов: очистка DOM между кейсами (WCAG-проверки — в Playwright).
afterEach(() => {
  cleanup();
});
