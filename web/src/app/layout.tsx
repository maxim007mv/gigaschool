/**
 * Общий каркас экрана: шапка с навигацией, рабочая область, баннер офлайна.
 * Пять шагов жизненного цикла программы показываются на страницах Stepper-ом.
 */

import { useEffect, useState } from "react";
import { Link, Outlet } from "@tanstack/react-router";

import { T } from "../shared/i18n/ru";
import { useMe } from "../shared/api/queries";

export function AppLayout() {
  const online = useOnlineStatus();
  const me = useMe();
  const roleLabel =
    me.data?.role === "head"
      ? "Руководитель"
      : me.data?.role === "expert"
        ? "Эксперт"
        : me.data?.role === "admin"
          ? "Администратор"
          : T.nav.role;

  return (
    <div className="min-h-screen bg-canvas">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-[1200px] flex-wrap items-center justify-between gap-md px-xl py-md">
          <div className="flex items-baseline gap-md">
            <Link to="/" className="text-title font-bold text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary">
              {T.app.title}
            </Link>
            <span className="text-caption text-ink-muted">{T.app.subtitle}</span>
          </div>
          <nav aria-label="Основная навигация" className="flex items-center gap-lg">
            <Link
              to="/"
              className="text-base text-ink hover:text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
              activeProps={{ className: "font-semibold text-primary" }}
            >
              {T.nav.programs}
            </Link>
            <Link
              to="/kb"
              className="text-base text-ink hover:text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
              activeProps={{ className: "font-semibold text-primary" }}
            >
              {T.nav.kb}
            </Link>
            <span className="rounded-full bg-primary-bg px-md py-xs text-caption font-medium text-primary">
              {roleLabel}
            </span>
          </nav>
        </div>
      </header>

      {!online ? (
        <div role="status" className="border-b border-warning/30 bg-warning-bg px-xl py-sm text-center text-base text-warning">
          {T.app.offline}
        </div>
      ) : null}

      <main className="mx-auto flex max-w-[1200px] flex-col gap-xl px-xl py-xl">
        <Outlet />
      </main>
    </div>
  );
}

function useOnlineStatus(): boolean {
  const [online, setOnline] = useState(() =>
    typeof navigator === "undefined" ? true : navigator.onLine,
  );

  useEffect(() => {
    const handleOnline = () => setOnline(true);
    const handleOffline = () => setOnline(false);
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  return online;
}
