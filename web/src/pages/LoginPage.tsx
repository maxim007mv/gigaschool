/**
 * Вход методиста: JWT access/refresh в localStorage (Д4 §8).
 * Без экрана входа после истечения access (15 мин) UI показывает «Не удалось загрузить данные».
 */

import { useState, type FormEvent } from "react";
import { useNavigate } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";

import { ApiError, apiFetch, clearAuthTokens, setAccessToken, setRefreshToken } from "../shared/api/client";
import { T } from "../shared/i18n/ru";
import { Button } from "../shared/ui/Button";

const DEMO_EMAIL = "methodist@acr-demo.example";
const DEMO_PASSWORD = "demo1234";

export function LoginPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [email, setEmail] = useState(DEMO_EMAIL);
  const [password, setPassword] = useState(DEMO_PASSWORD);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      clearAuthTokens();
      const { data } = await apiFetch<{
        access_token: string;
        refresh_token: string;
      }>("/auth/login", {
        method: "POST",
        body: { email, password },
      });
      setAccessToken(data.access_token);
      setRefreshToken(data.refresh_token);
      await queryClient.clear();
      await navigate({ to: "/" });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : T.auth.failed);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto flex max-w-md flex-col gap-lg py-xl">
      <header className="flex flex-col gap-xs">
        <h1 className="text-title font-bold text-ink">{T.auth.title}</h1>
        <p className="text-base text-ink-muted">{T.auth.subtitle}</p>
      </header>

      <form className="flex flex-col gap-md rounded-card border border-line bg-surface p-lg" onSubmit={submit}>
        <label className="flex flex-col gap-xs text-caption text-ink-muted">
          {T.auth.email}
          <input
            type="email"
            autoComplete="username"
            className="rounded-btn border border-line px-md py-sm text-base text-ink"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </label>
        <label className="flex flex-col gap-xs text-caption text-ink-muted">
          {T.auth.password}
          <input
            type="password"
            autoComplete="current-password"
            className="rounded-btn border border-line px-md py-sm text-base text-ink"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {error ? (
          <p role="alert" className="rounded-btn bg-danger-bg px-md py-sm text-caption text-danger">
            {error}
          </p>
        ) : null}
        <Button type="submit" variant="primary" busy={busy} disabled={busy}>
          {T.auth.submit}
        </Button>
      </form>
    </div>
  );
}
