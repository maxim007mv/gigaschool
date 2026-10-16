/**
 * HTTP-клиент API КАРКАС: fetch-обёртка над /api/v1 (Д4 §6.1).
 *
 * - ошибки — RFC 9457 problem+json (см. problem.ts);
 * - ETag/If-Match — защита от одновременного редактирования (412);
 * - Idempotency-Key для задач, которые нельзя запускать дважды;
 * - длительные операции сервер отдаёт как 202 + job_id.
 */

import { problemMessage, type ProblemDetails } from "./problem";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly problem: ProblemDetails;

  constructor(status: number, problem: ProblemDetails) {
    super(problemMessage(problem));
    this.name = "ApiError";
    this.status = status;
    this.code = problem.code ?? null;
    this.problem = problem;
  }
}

export interface ApiFetchOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  /** Тело запроса: сериализуется в JSON (кроме FormData). */
  body?: unknown;
  headers?: Record<string, string>;
  /** Query-параметры; undefined-значения пропускаются. */
  query?: Record<string, string | number | undefined>;
  /** If-Match: значение ETag текущей версии (защита от конфликта версий). */
  ifMatch?: string | null;
  /** Idempotency-Key: повторный POST не создаст вторую задачу. */
  idempotencyKey?: string;
  signal?: AbortSignal;
}

export interface ApiResponse<T> {
  data: T;
  status: number;
  etag: string | null;
}

const API_BASE: string = import.meta.env.VITE_API_BASE ?? "/api/v1";

/** Полный путь запроса с query-параметрами. */
export function apiUrl(path: string, query?: ApiFetchOptions["query"]): string {
  const base = `${API_BASE}${path}`;
  if (!query) return base;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${base}?${qs}` : base;
}

const ACCESS_KEY = "karkas.access_token";
const REFRESH_KEY = "karkas.refresh_token";

/** Токен доступа (JWT) из localStorage; в демо может отсутствовать. */
export function getAccessToken(): string | null {
  try {
    return window.localStorage.getItem(ACCESS_KEY);
  } catch {
    return null;
  }
}

export function setAccessToken(token: string | null): void {
  try {
    if (token) window.localStorage.setItem(ACCESS_KEY, token);
    else window.localStorage.removeItem(ACCESS_KEY);
  } catch {
    // private mode
  }
}

export function setRefreshToken(token: string | null): void {
  try {
    if (token) window.localStorage.setItem(REFRESH_KEY, token);
    else window.localStorage.removeItem(REFRESH_KEY);
  } catch {
    // private mode
  }
}

export function clearAuthTokens(): void {
  setAccessToken(null);
  setRefreshToken(null);
}

/**
 * Ключ идемпотентности для POST, создающих задачи (Д4 §6.1):
 * повторный вызов с тем же ключом не создаст вторую задачу.
 */
export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `idem-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function parseProblem(response: Response): Promise<ProblemDetails> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object") return body as ProblemDetails;
  } catch {
    // Тело не JSON — вернём минимальное описание.
  }
  return { status: response.status, title: response.statusText };
}

/** Основная обёртка: JSON-запрос к API с обработкой problem+json. */
export async function apiFetch<T>(path: string, options: ApiFetchOptions = {}): Promise<ApiResponse<T>> {
  const headers: Record<string, string> = {
    Accept: "application/json, application/problem+json",
    ...options.headers,
  };
  if (options.ifMatch) headers["If-Match"] = options.ifMatch;
  if (options.idempotencyKey) headers["Idempotency-Key"] = options.idempotencyKey;
  const token = getAccessToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let body: BodyInit | undefined;
  if (options.body !== undefined) {
    headers["Content-Type"] = headers["Content-Type"] ?? "application/json";
    body = JSON.stringify(options.body);
  }

  const response = await fetch(apiUrl(path, options.query), {
    method: options.method ?? "GET",
    headers,
    body,
    signal: options.signal,
  });

  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/auth/")) {
      clearAuthTokens();
      if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
        window.location.assign("/login");
      }
    }
    throw new ApiError(response.status, await parseProblem(response));
  }

  const data = response.status === 204 ? (undefined as T) : ((await response.json()) as T);
  return { data, status: response.status, etag: response.headers.get("ETag") };
}

/** Загрузка файла: POST /files с multipart/form-data. */
export async function apiUpload<T>(
  path: string,
  file: File,
  fields: Record<string, string> = {},
): Promise<ApiResponse<T>> {
  const form = new FormData();
  form.append("file", file);
  for (const [key, value] of Object.entries(fields)) form.append(key, value);

  const headers: Record<string, string> = { Accept: "application/json, application/problem+json" };
  const token = getAccessToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const response = await fetch(apiUrl(path), { method: "POST", headers, body: form });
  if (!response.ok) {
    throw new ApiError(response.status, await parseProblem(response));
  }
  const data = (await response.json()) as T;
  return { data, status: response.status, etag: response.headers.get("ETag") };
}

/** Значение ETag для If-Match: как пришло, либо null. */
export type { ProblemDetails };
