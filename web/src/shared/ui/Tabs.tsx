/**
 * Вкладки на Radix Tabs (Д3 §7): роли tablist/tab/tabpanel, управление
 * стрелками — из коробки.
 */

import * as TabsPrimitive from "@radix-ui/react-tabs";
import type { ReactNode } from "react";
import { cx } from "./cx";

export const Tabs = TabsPrimitive.Root;

export function TabsList({ children, className, label }: { children: ReactNode; className?: string; label: string }) {
  return (
    <TabsPrimitive.List
      aria-label={label}
      className={cx("flex gap-xs border-b border-line", className)}
    >
      {children}
    </TabsPrimitive.List>
  );
}

export function TabsTrigger({
  value,
  children,
  disabledReason,
}: {
  value: string;
  children: ReactNode;
  disabledReason?: string;
}) {
  return (
    <TabsPrimitive.Trigger
      value={value}
      disabled={Boolean(disabledReason)}
      title={disabledReason}
      className={cx(
        "px-lg py-sm text-base font-medium text-ink-muted",
        "border-b-2 border-transparent -mb-px",
        "hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary",
        "data-[state=active]:border-primary data-[state=active]:text-primary",
        "disabled:cursor-not-allowed disabled:opacity-60",
      )}
    >
      {children}
    </TabsPrimitive.Trigger>
  );
}

export function TabsContent({ value, children, className }: { value: string; children: ReactNode; className?: string }) {
  return (
    <TabsPrimitive.Content
      value={value}
      className={cx("pt-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary", className)}
    >
      {children}
    </TabsPrimitive.Content>
  );
}
