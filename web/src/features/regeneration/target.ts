/**
 * Какую часть комплекта можно пересобрать для выбранного элемента.
 *
 * Бэкенд `POST /kit:regenerate` принимает только тему (T*) или модуль (M*).
 * Разделы шаблона и аннотация пересобираются вместе с модулем, поэтому для
 * них кнопка блокируется с понятным объяснением.
 */

import type { ContentBlock } from "../../entities/kit";

export type RegenerationPart = "module_program" | "lecture_plan" | "slides" | "tests" | "tasks";

export type RegenerationSelection =
  | { kind: "block"; block: ContentBlock }
  | { kind: "assessments"; moduleRef: string | null }
  | { kind: "sources" }
  | { kind: "final" }
  | null;

export interface RegenerationTarget {
  ref: string;
  kind: "module" | "topic";
  parts: RegenerationPart[];
}

export interface RegenerationOption {
  target: RegenerationTarget | null;
  allowed: boolean;
  reason?: string;
}

export function regenerationFor(selection: RegenerationSelection): RegenerationOption {
  if (!selection) {
    return { target: null, allowed: false, reason: "Сначала выберите тему или модуль слева" };
  }

  if (selection.kind === "assessments") {
    if (!selection.moduleRef) {
      return { target: null, allowed: false, reason: "Сначала выберите модуль" };
    }
    return {
      target: { ref: selection.moduleRef, kind: "module", parts: ["slides", "tests", "lecture_plan"] },
      allowed: true,
    };
  }

  if (selection.kind !== "block") {
    return { target: null, allowed: false, reason: "Сначала выберите тему или модуль слева" };
  }

  const { block } = selection;

  if (block.kind === "module_program" && block.module_ref) {
    return {
      target: { ref: block.module_ref, kind: "module", parts: ["module_program"] },
      allowed: true,
    };
  }

  if ((block.kind === "lecture_plan" || block.kind === "slides") && block.topic_ref) {
    return {
      target: {
        ref: block.topic_ref,
        kind: "topic",
        parts: [block.kind === "slides" ? "slides" : "lecture_plan"],
      },
      allowed: true,
    };
  }

  if (block.kind === "template_section") {
    return {
      target: null,
      allowed: false,
      reason: "Раздел программы пересобирается вместе с модулем: выберите тему или модуль слева.",
    };
  }

  if (block.kind === "annotation") {
    return {
      target: null,
      allowed: false,
      reason: "Аннотация пересобирается вместе с программой: выберите тему или модуль слева.",
    };
  }

  return { target: null, allowed: false, reason: "Сначала выберите тему или модуль слева" };
}
