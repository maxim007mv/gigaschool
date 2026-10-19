/**
 * Экранные состояния фоновой сборки: «ждём каркас» и «ждём комплект»
 * не должны показываться как ошибка или предлагать повторный запуск.
 */

import type { ReactNode } from "react";
import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../shared/api/client";
import type { ProgramEvent } from "../shared/api/sse";
import { ToastProvider } from "../shared/ui/Toast";
import { FrameworkPage } from "./FrameworkPage";
import { KitPage } from "./KitPage";

const hooks = vi.hoisted(() => ({
  useProgram: vi.fn(),
  useFramework: vi.fn(),
  useKit: vi.fn(),
  useProgramEvents: vi.fn(),
  useGenerateFramework: vi.fn(),
  useGenerateKit: vi.fn(),
  useCreateEdit: vi.fn(),
  useRegenerateKitPart: vi.fn(),
  useExport: vi.fn(),
  useExportStatus: vi.fn(),
  useUsage: vi.fn(),
  useApproveFramework: vi.fn(),
  useRebalanceFramework: vi.fn(),
  useRestoreVersion: vi.fn(),
  useSaveFramework: vi.fn(),
}));

vi.mock("@tanstack/react-router", () => ({
  useParams: () => ({ programId: "p-1" }),
  Link: ({ children }: { children?: ReactNode }) => children,
}));

vi.mock("../shared/api/queries", () => ({
  STATUS_POLL_INTERVAL_MS: 2500,
  USE_MOCKS: true,
  useProgram: hooks.useProgram,
  useFramework: hooks.useFramework,
  useKit: hooks.useKit,
  useProgramEvents: hooks.useProgramEvents,
  useGenerateFramework: hooks.useGenerateFramework,
  useGenerateKit: hooks.useGenerateKit,
  useCreateEdit: hooks.useCreateEdit,
  useRegenerateKitPart: hooks.useRegenerateKitPart,
  useExport: hooks.useExport,
  useExportStatus: hooks.useExportStatus,
  useUsage: hooks.useUsage,
  useApproveFramework: hooks.useApproveFramework,
  useRebalanceFramework: hooks.useRebalanceFramework,
  useRestoreVersion: hooks.useRestoreVersion,
  useSaveFramework: hooks.useSaveFramework,
}));

function mutation() {
  return { mutateAsync: vi.fn(), isPending: false };
}

function query<T>(data: T | undefined, error?: unknown) {
  return {
    data,
    isPending: false,
    isError: Boolean(error),
    error,
    refetch: vi.fn(),
  };
}

let latestEventHandler: ((event: ProgramEvent) => void) | null = null;

beforeEach(() => {
  vi.clearAllMocks();
  latestEventHandler = null;
  hooks.useProgramEvents.mockImplementation(
    (_programId: string | null, handler: (event: ProgramEvent) => void) => {
      latestEventHandler = handler;
    },
  );
  hooks.useGenerateFramework.mockReturnValue(mutation());
  hooks.useGenerateKit.mockReturnValue(mutation());
  hooks.useCreateEdit.mockReturnValue(mutation());
  hooks.useRegenerateKitPart.mockReturnValue(mutation());
  hooks.useExport.mockReturnValue(mutation());
  hooks.useExportStatus.mockReturnValue({ data: null });
  hooks.useUsage.mockReturnValue({ isPending: true, data: undefined });
  hooks.useApproveFramework.mockReturnValue(mutation());
  hooks.useRebalanceFramework.mockReturnValue(mutation());
  hooks.useRestoreVersion.mockReturnValue(mutation());
  hooks.useSaveFramework.mockReturnValue(mutation());
});

describe("ожидание фоновой сборки", () => {
  it("каркас: показывает прогресс, а не ошибку 404", () => {
    hooks.useProgram.mockReturnValue(query({ status: "framework_generating" }));
    hooks.useFramework.mockReturnValue(
      query(undefined, new ApiError(404, { code: "NOT_FOUND", detail: "Каркас ещё не собран" })),
    );

    render(
      <ToastProvider>
        <FrameworkPage />
      </ToastProvider>,
    );

    expect(screen.getByRole("heading", { name: "Собираем каркас" })).toBeInTheDocument();
    expect(screen.queryByText(/Не удалось открыть каркас/)).not.toBeInTheDocument();
  });

  it("каркас: окончательная ошибка объясняет причину и даёт повторить", () => {
    hooks.useProgram.mockReturnValue(query({ status: "framework_generating" }));
    hooks.useFramework.mockReturnValue(
      query(undefined, new ApiError(404, { code: "NOT_FOUND", detail: "Каркас ещё не собран" })),
    );

    render(
      <ToastProvider>
        <FrameworkPage />
      </ToastProvider>,
    );

    act(() => {
      latestEventHandler?.({
        name: "job_failed",
        payload: {
          job_id: "job-1",
          code: "LLM_UNAVAILABLE",
          detail: "Сервис сборки временно недоступен",
          will_retry: false,
        },
      });
    });

    expect(screen.getByRole("alert")).toHaveTextContent("Сервис сборки временно недоступен");
    expect(
      screen.getByRole("button", { name: "Повторить сборку каркаса" }),
    ).toBeInTheDocument();
  });

  it("комплект: во время kit_generating не предлагает собрать заново", () => {
    hooks.useProgram.mockReturnValue(query({ status: "kit_generating" }));
    hooks.useKit.mockReturnValue(
      query(
        undefined,
        new ApiError(409, { code: "GATE_NOT_PASSED", detail: "Сначала утвердите каркас" }),
      ),
    );
    hooks.useFramework.mockReturnValue(query({ status: "kit_generating" }));

    render(
      <ToastProvider>
        <KitPage />
      </ToastProvider>,
    );

    expect(screen.getByRole("heading", { name: "Собираем комплект" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Собрать комплект" })).not.toBeInTheDocument();
    expect(screen.queryByText("Сначала утвердите каркас")).not.toBeInTheDocument();
  });
});
