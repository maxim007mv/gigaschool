/**
 * Правила точечной пересборки: бэкенд принимает только темы и модули,
 * разделы шаблона пересобираются вместе с модулем.
 */

import { describe, expect, it } from "vitest";

import type { ContentBlock } from "../../entities/kit";
import { regenerationFor } from "./target";

function block(overrides: Partial<ContentBlock>): ContentBlock {
  return {
    ref: "T1.1",
    kind: "lecture_plan",
    module_ref: "M1",
    topic_ref: "T1.1",
    body: {},
    generated_by: "S12",
    stale: false,
    ...overrides,
  };
}

describe("regenerationFor", () => {
  it("для темы отправляет ref темы", () => {
    const result = regenerationFor({ kind: "block", block: block({}) });
    expect(result.allowed).toBe(true);
    expect(result.target).toEqual({ ref: "T1.1", kind: "topic", parts: ["lecture_plan"] });
  });

  it("для рабочей программы модуля отправляет ref модуля", () => {
    const result = regenerationFor({
      kind: "block",
      block: block({ ref: "MP-M2", kind: "module_program", topic_ref: null, module_ref: "M2" }),
    });
    expect(result.allowed).toBe(true);
    expect(result.target).toEqual({ ref: "M2", kind: "module", parts: ["module_program"] });
  });

  it("для раздела шаблона блокирует пересборку и объясняет причину", () => {
    const result = regenerationFor({
      kind: "block",
      block: block({
        ref: "SEC-3.1",
        kind: "template_section",
        module_ref: null,
        topic_ref: null,
      }),
    });
    expect(result.allowed).toBe(false);
    expect(result.target).toBeNull();
    expect(result.reason).toContain("вместе с модулем");
  });

  it("для оценочных средств пересобирает выбранный модуль", () => {
    const result = regenerationFor({ kind: "assessments", moduleRef: "M1" });
    expect(result.allowed).toBe(true);
    expect(result.target?.kind).toBe("module");
    expect(result.target?.ref).toBe("M1");
  });
});
