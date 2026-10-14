/**
 * SSE-клиент потока событий программы: GET /programs/{id}/events (Д4 §6.7).
 *
 * События: progress, needs_input, framework_ready, kit_ready, edit_applied,
 * export_ready, job_failed. При обрыве — переподключение с Last-Event-ID,
 * чтобы сервер продолжил поток без потери событий.
 */

import { getAccessToken } from "./client";

export interface ProgressEventData {
  job_id: string;
  /** Код шага навыка, например "S07". */
  step: string;
  /** Человеческая подпись: «Строим модули и темы». */
  label: string;
  done: number;
  total: number;
}

export interface NeedsInputEventData {
  questions_url: string;
}

export interface FrameworkReadyEventData {
  version: number;
  checks: { passed: boolean };
}

export interface KitReadyEventData {
  version: number;
  report: { passed: boolean };
}

export interface EditAppliedEventData {
  edit_id: string;
  version: number;
  changed_refs: string[];
}

export interface ExportReadyEventData {
  export_id: string;
}

export interface JobFailedEventData {
  job_id: string;
  code: string;
  detail: string;
  will_retry: boolean;
}

/** Соответствие «имя события → данные» (Д4 §6.7, таблица 4.12). */
export interface ProgramEventMap {
  progress: ProgressEventData;
  needs_input: NeedsInputEventData;
  framework_ready: FrameworkReadyEventData;
  kit_ready: KitReadyEventData;
  edit_applied: EditAppliedEventData;
  export_ready: ExportReadyEventData;
  job_failed: JobFailedEventData;
}

export type ProgramEventName = keyof ProgramEventMap;

/** Событие с дискриминатором: switch по event.name сужает тип payload. */
export type ProgramEvent =
  | { name: "progress"; payload: ProgressEventData }
  | { name: "needs_input"; payload: NeedsInputEventData }
  | { name: "framework_ready"; payload: FrameworkReadyEventData }
  | { name: "kit_ready"; payload: KitReadyEventData }
  | { name: "edit_applied"; payload: EditAppliedEventData }
  | { name: "export_ready"; payload: ExportReadyEventData }
  | { name: "job_failed"; payload: JobFailedEventData };

export const PROGRAM_EVENT_NAMES: ReadonlyArray<ProgramEventName> = [
  "progress",
  "needs_input",
  "framework_ready",
  "kit_ready",
  "edit_applied",
  "export_ready",
  "job_failed",
];

export interface ProgramEventStreamOptions {
  /** Базовый путь API; по умолчанию /api/v1 (как в client.ts). */
  baseUrl?: string;
  /** Последний полученный id события (для продолжения потока). */
  lastEventId?: string | null;
  /** Максимум попыток переподключения (далее — onGiveUp). */
  maxRetries?: number;
  onEvent: (event: ProgramEvent) => void;
  onOpen?: () => void;
  onReconnect?: (attempt: number) => void;
  onGiveUp?: (lastError: Event) => void;
}

/**
 * Поток событий одной программы.
 *
 * Браузерный EventSource сам шлёт заголовок Last-Event-ID при переподключении;
 * дополнительно мы передаём его query-параметром — так серверу проще
 * восстановить поток за прокси, которые заголовок не пробрасывают.
 */
export class ProgramEventStream {
  private readonly baseUrl: string;
  private readonly emit: (event: ProgramEvent) => void;
  private source: EventSource | null = null;
  private lastEventId: string | null;
  private attempt = 0;
  private closed = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private readonly programId: string,
    private readonly options: ProgramEventStreamOptions,
  ) {
    this.baseUrl = options.baseUrl ?? import.meta.env.VITE_API_BASE ?? "/api/v1";
    this.lastEventId = options.lastEventId ?? null;
    this.emit = options.onEvent;
  }

  /** Последний полученный id события (сохраняется между переподключениями). */
  get lastId(): string | null {
    return this.lastEventId;
  }

  connect(): void {
    if (this.closed) return;
    const params = new URLSearchParams();
    if (this.lastEventId) params.set("last_event_id", this.lastEventId);
    // EventSource не умеет ставить заголовки, поэтому токен передаём query-параметром
    // (сервер принимает и его, и Authorization — karkas/api/routers/programs.py).
    const token = getAccessToken();
    if (token) params.set("token", token);
    const qs = params.toString();
    const url = `${this.baseUrl}/programs/${encodeURIComponent(this.programId)}/events${qs ? `?${qs}` : ""}`;

    const source = new EventSource(url);
    this.source = source;

    source.onopen = () => {
      this.attempt = 0;
      this.options.onOpen?.();
    };

    source.onerror = (event: Event) => {
      // EventSource переподключается сам; если соединение закрыто — пробуем вручную
      // с прежним Last-Event-ID и нарастающей паузой.
      if (source.readyState === EventSource.CLOSED) this.scheduleReconnect(event);
    };

    for (const name of PROGRAM_EVENT_NAMES) {
      source.addEventListener(name, (event: Event) => {
        const message = event as MessageEvent<string>;
        if (message.lastEventId) this.lastEventId = message.lastEventId;
        const parsed = parseEventPayload(message.data);
        if (parsed === null) return;
        // Имя события и форма payload заданы сервером (Д4 §6.7);
        // объединение ProgramEvent делает это соответствие явным для кода-потребителя.
        this.emit({ name, payload: parsed } as ProgramEvent);
      });
    }
  }

  close(): void {
    this.closed = true;
    if (this.reconnectTimer !== null) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.source?.close();
    this.source = null;
  }

  private scheduleReconnect(event: Event): void {
    if (this.closed) return;
    const maxRetries = this.options.maxRetries ?? 5;
    if (this.attempt >= maxRetries) {
      this.closed = true;
      this.options.onGiveUp?.(event);
      return;
    }
    this.attempt += 1;
    const delay = Math.min(30_000, 1_000 * 2 ** (this.attempt - 1));
    this.options.onReconnect?.(this.attempt);
    this.source?.close();
    this.reconnectTimer = setTimeout(() => this.connect(), delay);
  }
}

function parseEventPayload(raw: string): unknown | null {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    return null;
  }
}

/** Удобная обёртка: создать и сразу подключить поток. */
export function openProgramEvents(
  programId: string,
  options: ProgramEventStreamOptions,
): ProgramEventStream {
  const stream = new ProgramEventStream(programId, options);
  stream.connect();
  return stream;
}
