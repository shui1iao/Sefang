import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { currentSession, safeNext, sessionCheck, setSession, writeJson, type Account, type Session } from "./auth-client";
import { readJson } from "./data";

export function Login() {
  const [username, name] = useState(""), [password, pass] = useState(""), [error, fail] = useState(""), [busy, wait] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault(); wait(true); fail("");
    try {
      setSession(await writeJson<Session>("/api/auth/login", { username, password }));
      window.location.replace(safeNext(new URLSearchParams(window.location.search).get("next")));
    } catch (e) { fail(e instanceof Error ? e.message : "登录未完成"); }
    finally { pass(""); wait(false); }
  }
  return <main className="login-shell"><section className="account-panel login-panel">
    <div className="brand login-brand"><img className="brand-icon" src="/assets/sefang-icon-836f1222d7b86f34.svg" alt="" /><img className="brand-wordmark" src="/assets/sefang-wordmark-b563570aba759b24.svg" alt="Sefang" /></div>
    <h1>登录</h1><p className="muted">登录后浏览与播放。账号由管理员创建。</p>
    <form onSubmit={submit} className="account-form">
      <label>账号<input name="username" autoComplete="username" autoCapitalize="none" spellCheck={false} maxLength={32} required value={username} onChange={e => name(e.target.value)} /></label>
      <label>密码<input name="password" type="password" autoComplete="current-password" maxLength={256} required value={password} onChange={e => pass(e.target.value)} /></label>
      {error && <p className="account-error" role="alert">{error}</p>}
      <button className="account-primary" disabled={busy}>{busy ? "正在登录…" : "登录"}</button>
    </form>
  </section></main>;
}

export function AccountActions() {
  const me = currentSession();
  return <div className="account-actions" aria-label="账号"><Link to="/history">播放历史</Link>{me?.role === "admin" && <Link to="/admin/accounts">{me.username}</Link>}<button type="button" onClick={async () => { try { await writeJson("/api/auth/logout", {}); setSession(null); window.location.replace("/login"); } catch { await sessionCheck(); } }}>退出</button></div>;
}

function Limits({ rate, max, unlimited, onRate, onMax, onUnlimited }: { rate: string; max: string; unlimited: boolean; onRate: (s: string) => void; onMax: (s: string) => void; onUnlimited: (b: boolean) => void }) {
  return <><label>合计限速（MiB/s）<input type="number" min="0.000001" step="any" required={!unlimited} disabled={unlimited} value={rate} onChange={e => onRate(e.target.value)} /><span className="muted field-hint">1 MiB/s = 1048576 bytes/s；所有连接合计</span></label><label className="check-label"><input type="checkbox" checked={unlimited} onChange={e => onUnlimited(e.target.checked)} />不限速</label><label>同时播放上限<input type="number" min="1" max="2147483647" step="1" required value={max} onChange={e => onMax(e.target.value)} /><span className="muted field-hint">必填；同播放器拖动不重复计数</span></label></>;
}
function limitValues(rate: string, max: string, unlimited: boolean) {
  const maximum = Number(max), bps = Math.round(Number(rate) * 1048576);
  if (!max || !Number.isSafeInteger(maximum) || maximum < 1 || maximum > 2147483647 || (!unlimited && (!rate || !Number.isSafeInteger(bps) || bps < 1 || bps > 2**40))) throw Error("请填写有效的 MiB/s 限速和整数播放上限");
  return { rate_bps: unlimited ? null : bps, max_playbacks: maximum };
}
function CreateAccount({ done }: { done: () => void }) {
  const [username, name] = useState(""), [password, pass] = useState(""), [rate, speed] = useState("2"), [max, maximum] = useState(""), [unlimited, unlimit] = useState(false), [error, fail] = useState(""), [busy, wait] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault(); wait(true); fail("");
    try { await writeJson("/api/admin/accounts", { username, password, ...limitValues(rate, max, unlimited) }); pass(""); name(""); maximum(""); done(); }
    catch (e) { fail(e instanceof Error ? e.message : "创建未完成"); }
    finally { wait(false); }
  }
  return <section className="account-panel"><h2>创建普通账号</h2><form className="account-form account-create" onSubmit={submit}>
    <label>账号<input required autoComplete="off" autoCapitalize="none" pattern="[a-z][a-z0-9_.\-]{2,31}" minLength={3} maxLength={32} value={username} onChange={e => name(e.target.value)} /><span className="muted field-hint">3–32 位，小写字母开头，可含数字 . _ -</span></label>
    <label>初始密码<input type="password" autoComplete="new-password" minLength={12} maxLength={256} required value={password} onChange={e => pass(e.target.value)} /><span className="muted field-hint">12–256 个字符；仅此次填写，不显示在列表</span></label>
    <Limits rate={rate} max={max} unlimited={unlimited} onRate={speed} onMax={maximum} onUnlimited={unlimit} />
    <div className="account-form-end">{error && <p className="account-error" role="alert">{error}</p>}<button className="account-primary" disabled={busy}>{busy ? "正在创建…" : "创建账号"}</button></div>
  </form></section>;
}
function AccountRow({ account: a, done }: { account: Account; done: () => void }) {
  const [edit, editing] = useState(false), [reset, resetting] = useState(false), [rate, speed] = useState(String((a.rate_bps ?? 2097152) / 1048576)), [max, maximum] = useState(String(a.max_playbacks)), [unlimited, unlimit] = useState(a.rate_bps === null), [password, pass] = useState(""), [error, fail] = useState(""), [busy, wait] = useState(false), [confirm, confirming] = useState(false);
  async function action(work: () => Promise<unknown>) {
    wait(true); fail("");
    try { await work(); editing(false); resetting(false); confirming(false); pass(""); done(); }
    catch (e) { fail(e instanceof Error ? e.message : "操作未完成"); }
    finally { wait(false); }
  }
  return <article className="account-panel account-row"><div className="account-summary"><div><h3>{a.username} <span className="account-badge">{a.role === "admin" ? "管理员" : a.enabled ? "已启用" : "已停用"}</span></h3><p className="muted">{a.rate_bps === null ? "不限速" : `${a.rate_bps / 1048576} MiB/s 合计`}<span aria-hidden="true"> · </span>同时播放 {a.max_playbacks}</p></div><div className="account-row-actions"><button disabled={busy} onClick={() => { editing(!edit); resetting(false); }}>编辑限制</button><button disabled={busy} onClick={() => { resetting(!reset); editing(false); pass(""); }}>重置密码</button>{a.role !== "admin" && <button disabled={busy} onClick={() => confirming(!confirm)}>{a.enabled ? "停用" : "启用"}</button>}</div></div>
    {confirm && <div className="account-confirm"><p>{a.enabled ? "停用后，该账号所有登录和活动取流将立即撤销。" : "确认恢复此账号登录？"}</p><button disabled={busy} className="account-danger" onClick={() => action(() => writeJson(`/api/admin/accounts/${a.id}`, { enabled: !a.enabled }, "PATCH"))}>确认{a.enabled ? "停用" : "启用"}</button><button onClick={() => confirming(false)}>取消</button></div>}
    {edit && <form className="account-form account-edit" onSubmit={e => { e.preventDefault(); action(async () => writeJson(`/api/admin/accounts/${a.id}`, limitValues(rate, max, unlimited), "PATCH")); }}><Limits rate={rate} max={max} unlimited={unlimited} onRate={speed} onMax={maximum} onUnlimited={unlimit} /><button className="account-primary" disabled={busy}>保存限制</button></form>}
    {reset && <form className="account-form account-reset" onSubmit={e => { e.preventDefault(); action(() => writeJson(`/api/admin/accounts/${a.id}/password`, { password })); }}><label>新密码<input autoComplete="new-password" type="password" required minLength={12} maxLength={256} value={password} onChange={e => pass(e.target.value)} /></label><p className="muted">保存即撤销此账号全部旧登录和活动取流。</p><button disabled={busy} className="account-danger">确认重置密码</button></form>}
    {error && <p className="account-error" role="alert">{error}</p>}
  </article>;
}
export function Accounts() {
  const [items, list] = useState<Account[]>([]), [error, fail] = useState(""), [version, refresh] = useState(0), [loading, wait] = useState(true);
  const allowed = currentSession()?.role === "admin";
  useEffect(() => { if (!allowed) return; const abort = new AbortController(); wait(true); readJson<{ items: Account[] }>("/api/admin/accounts", abort.signal).then(data => { list(data.items); fail(""); }, e => { if (!abort.signal.aborted) fail(e.message); }).finally(() => { if (!abort.signal.aborted) wait(false); }); return () => abort.abort(); }, [version, allowed]);
  if (!allowed) return <main className="container"><h1>无权访问</h1><Link to="/">返回全部视频</Link></main>;
  return <main className="container accounts-page"><div className="list-heading"><h1>账号管理</h1><p className="muted">仅管理员可创建和管理账号。停用、重置密码会撤销旧登录。</p></div><CreateAccount done={() => refresh(v => v + 1)} /><section className="account-list" aria-label="账号列表"><h2>全部账号</h2>{error && <p className="account-error" role="alert">{error}<button onClick={() => refresh(v => v + 1)}>重试</button></p>}{loading && <p className="muted" role="status">正在读取</p>}{items.map(a => <AccountRow key={`${a.id}:${version}`} account={a} done={() => refresh(v => v + 1)} />)}</section></main>;
}
