/**
 * Маршруты приложения (TanStack Router).
 *
 * Пять шагов жизненного цикла программы разложены по маршрутам:
 * /programs/new → /programs/{id}/clarify → /framework → /kit → выгрузки.
 */

import { createRootRoute, createRoute, createRouter, type RouterHistory } from "@tanstack/react-router";

import { AppLayout } from "./layout";
import { ProgramsPage } from "../pages/ProgramsPage";
import { IntakePage } from "../pages/IntakePage";
import { ClarifyPage } from "../pages/ClarifyPage";
import { FrameworkPage } from "../pages/FrameworkPage";
import { KitPage } from "../pages/KitPage";
import { VersionsPage } from "../pages/VersionsPage";
import { KbPage } from "../pages/KbPage";
import { ActualizePage } from "../pages/ActualizePage";
import { AdaptPage } from "../pages/AdaptPage";
import { LoginPage } from "../pages/LoginPage";

const rootRoute = createRootRoute({
  component: AppLayout,
});

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  component: LoginPage,
});

const programsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: ProgramsPage,
});

const intakeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/programs/new",
  component: IntakePage,
});

const clarifyRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/programs/$programId/clarify",
  component: ClarifyPage,
});

const frameworkRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/programs/$programId/framework",
  component: FrameworkPage,
});

const kitRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/programs/$programId/kit",
  component: KitPage,
});

const versionsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/programs/$programId/versions",
  component: VersionsPage,
});

const actualizeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/programs/$programId/actualize",
  component: ActualizePage,
});

const adaptRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/programs/$programId/adapt",
  component: AdaptPage,
});

const kbRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/kb",
  component: KbPage,
});

const routeTree = rootRoute.addChildren([
  loginRoute,
  programsRoute,
  intakeRoute,
  clarifyRoute,
  frameworkRoute,
  kitRoute,
  versionsRoute,
  actualizeRoute,
  adaptRoute,
  kbRoute,
]);

export const router = createRouter({
  routeTree,
  defaultPreload: "intent",
  scrollRestoration: true,
});

/** Регистрация роутера для типизации Link/useParams. */
declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
    history: RouterHistory;
  }
}
