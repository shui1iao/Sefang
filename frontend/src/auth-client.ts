export type Account = { id: number; username: string; role: "admin" | "user"; enabled: boolean; rate_bps: number | null; max_playbacks: number };
export type Session = Omit<Account, "enabled"> & { csrf: string };
let session: Session | null = null;
export const currentSession = () => session;
export const setSession = (value: Session | null) => { session = value; };

export function safeNext(value: string | null): string {
  if (!value || value.length > 2048 || (value.includes("\\") || Array.from(value).some(c => c.charCodeAt(0) <= 32)) || !value.startsWith("/") || value.startsWith("//")) return "/";
  const url = new URL(value, window.location.origin);
  if (url.origin !== window.location.origin || !/^\/(?:|actors(?:\/[a-f0-9]{24})?|categories(?:\/[a-f0-9]{24})?|studios(?:\/[a-f0-9]{24})?|watch\/\d+\/\d+|admin\/accounts|history)$/.test(url.pathname)) return "/";
  return url.pathname + url.search;
}
export function requireLogin() {
  session = null;
  if (window.location.pathname !== "/login") window.location.replace("/login?next=" + encodeURIComponent(safeNext(window.location.pathname + window.location.search)));
}
export async function sessionCheck(): Promise<Session | null> {
  const response = await fetch("/api/auth/me", { cache: "no-store" });
  if (response.status === 401) { requireLogin(); return null; }
  if (!response.ok) throw Error("登录状态未取得，请刷新重试");
  session = await response.json() as Session;
  return session;
}
export async function writeJson<T = { ok: boolean }>(path: string, body: unknown, method: "POST" | "PATCH" = "POST"): Promise<T> {
  const response = await fetch(path, { method, cache: "no-store", headers: { "Content-Type": "application/json", ...(session ? { "X-CSRF-Token": session.csrf } : {}) }, body: JSON.stringify(body) });
  if (response.status === 401 && path !== "/api/auth/login") requireLogin();
  const data = await response.json();
  if (!response.ok) throw Error(typeof data.detail === "string" ? data.detail : "请求未完成，请重试");
  return data as T;
}
