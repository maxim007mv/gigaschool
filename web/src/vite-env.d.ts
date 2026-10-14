/// <reference types="vite/client" />

// Переменные окружения сборки (см. vite.config.ts).
interface ImportMetaEnv {
  /** Базовый путь API, по умолчанию /api/v1 */
  readonly VITE_API_BASE?: string;
  /** "0" — отключить моки в dev-режиме и ходить в реальный API */
  readonly VITE_USE_MOCKS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
