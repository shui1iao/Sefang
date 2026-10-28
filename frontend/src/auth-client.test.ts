import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { currentSession, requireLogin, safeNext, sessionCheck, setSession, writeJson } from "./auth-client";

beforeEach(() => {
  setSession(null);
  vi.stubGlobal("window", { location: { origin: "https://test", pathname: "/watch/123/1", search: "?part=2", replace: vi.fn() } });
});
afterEach(() => vi.unstubAllGlobals());
describe("safe private-site navigation", () => {
  it("allows only known relative pages, retains safe queries", () => {
    for (const path of ["/", "/actors?page=2", "/categories?q=test", "/watch/123/1?part=2", "/admin/accounts"]) expect(safeNext(path)).toBe(path);
    for (const path of [null, "https://evil.test", "//evil.test", "/\\evil.test", "/%2f%2fevil.test", "/api/auth/logout", "/login", "/watch/123/1\n"]) expect(safeNext(path)).toBe("/");
  });
  it("clears in-memory identity and redirects with a relative next only", () => {
    requireLogin();
    expect(currentSession()).toBe(null);
    expect(window.location.replace).toHaveBeenCalledWith("/login?next=%2Fwatch%2F123%2F1%3Fpart%3D2");
  });
});
describe("authenticated request policy", () => {
  it("sends CSRF only in request headers and never puts credentials in URL", async () => {
    setSession({ id: 1, username: "fixture", role: "admin", csrf: "test-csrf", rate_bps: null, max_playbacks: 1 });
    const fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ ok: true }) }); vi.stubGlobal("fetch", fetch);
    await writeJson("/api/admin/accounts/2", { max_playbacks: 2 }, "PATCH");
    const [path, options] = fetch.mock.calls[0]; expect(path).toBe("/api/admin/accounts/2"); expect(options.headers["X-CSRF-Token"]).toBe("test-csrf"); expect(options.cache).toBe("no-store"); expect(options.method).toBe("PATCH");
  });
  it("expired asynchronous/active-player identity goes to login", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 401, json: async () => ({ detail: "请先登录" }) }));
    expect(await sessionCheck()).toBe(null); expect(window.location.replace).toHaveBeenCalled();
    await expect(writeJson("/api/playbacks", {})).rejects.toThrow("请先登录");
  });
  it("login errors stay on the login form", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 401, json: async () => ({ detail: "账号或密码不正确" }) }));
    await expect(writeJson("/api/auth/login", { username: "fixture", password: "test-only" })).rejects.toThrow("账号或密码不正确");
    expect(window.location.replace).not.toHaveBeenCalled();
  });
});
