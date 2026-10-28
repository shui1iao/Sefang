import { History } from "./History";
import type { Resume } from "./history-client";
import { Accounts, AccountActions, Login } from "./Accounts";
import { currentSession, sessionCheck } from "./auth-client";
import {
  Fragment,
  useCallback,
  useEffect,
  useState,
  type FormEvent,
} from "react";
import { createRoot } from "react-dom/client";
import {
  createBrowserRouter,
  Outlet,
  RouterProvider,
  Link,
  NavLink,
  useLoaderData,
  useNavigation,
  useRevalidator,
  useLocation,
  useNavigate,
  useParams,
} from "react-router";
import {
  KINDS,
  labels,
  filterKey,
  listLink,
  facetLink,
  hasSessionBack,
  normalizeQuery,
  safeLink,
  safeReturn,
  segmentState,
  validWatch,
  type Kind,
} from "./navigation";
import { partIndex } from "./segments";
import { Player } from "./Player";
import { FacetStrip, SortPicker } from "./pickers";
import {
  displayName,
  displayTitle,
  nameHint,
  translationLabel,
} from "./display";
import { useData, useScroll } from "./hooks";
import { Avatar, Icon, Loading, Message, Pages, VideoGrid } from "./components";
import type { Entity, Page, Video } from "./types";
import { loadDirectory, loadVideoList, type ListData, type DirectoryData } from "./loaders";
import { useCategoryPagination } from "./category-pagination";
import "./style.css";
import "./player.css";

const historyStart = history.state?.idx ?? 0;

function Header() {
  const navigation = useNavigation();
  const loc = useLocation(),
    navigate = useNavigate();
  const [q, setQ] = useState("");
  useEffect(
    () => setQ(new URLSearchParams(loc.search).get("q") || ""),
    [loc.search],
  );
  function submit(event: FormEvent) {
    event.preventDefault();
    navigate(listLink({ q }));
  }
  return (
    <header className="header">
      <div className="header-inner">
        <Link className="brand" to="/" aria-label="Sefang 首页">
          <img
            className="brand-icon"
            src="/assets/sefang-icon-836f1222d7b86f34.svg"
            width={29}
            height={29}
            alt=""
            aria-hidden="true"
          />
          <img
            className="brand-wordmark"
            src="/assets/sefang-wordmark-b563570aba759b24.svg"
            width={80.12}
            height={32}
            alt="Sefang"
          />
        </Link>
        <nav aria-label="主要导航" aria-busy={navigation.state !== "idle"}>
          <NavLink to="/" end>
            全部视频
          </NavLink>
          <NavLink to="/actors">演员</NavLink>
          <NavLink to="/categories">分类</NavLink>
          <NavLink to="/studios">发行商</NavLink>
        </nav>
        <form
          className="search"
          data-home-search={loc.pathname === "/" ? true : undefined}
          role="search"
          onSubmit={submit}
        >
          <Icon name="search" />
          <input
            aria-label="搜索番号、片名或演员"
            value={q}
            maxLength={300}
            onChange={(e) => setQ(e.target.value)}
            placeholder="番号、片名、演员"
          />
          <button type="submit" aria-label="搜索">
            <Icon name="arrow" />
          </button>
        </form>
        <AccountActions />
      </div>
    </header>
  );
}
function ActorStrip({
  selected,
  search,
}: {
  selected: string;
  search: string;
}) {
  const actors = useData<Page<Entity>>("/api/entities/actors?limit=100");
  const [expanded, setExpanded] = useState(false);
  return (
    <section className="actor-section" aria-label="按演员筛选">
      <div className="section-label">
        <span>选择演员</span>
        <Link to="/actors">
          全部演员 <span aria-hidden="true">↗</span>
        </Link>
      </div>
      <div className={"actor-strip" + (expanded ? " expanded" : "")}>
        <Link
          className={"actor-choice" + (!selected ? " selected" : "")}
          to={listLink({ actor: "" }, search)}
          aria-label="全部演员视频"
        >
          <span className="avatar all">全部</span>
          <span>全部演员</span>
        </Link>
        {actors.data?.items.map((actor) => (
          <Link
            key={actor.id}
            data-actor-id={actor.id}
            className={
              "actor-choice" + (selected === actor.id ? " selected" : "")
            }
            to={listLink({ actor: actor.id }, search)}
            title={nameHint(actor)}
            aria-label={displayName(actor)}
          >
            <Avatar entity={actor} />
            <span>{displayName(actor)}</span>
          </Link>
        ))}
        {actors.loading && <span className="muted">正在读取演员</span>}
      </div>
      {actors.error ? (
        <p className="muted">演员暂未取得，仍可浏览全部视频</p>
      ) : null}
      <button
        className="quiet expand"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        {expanded ? "收起头像" : "展开全部头像"}
      </button>
    </section>
  );
}
function VideoList({ kind, entityId }: { kind?: Kind; entityId?: string }) {
  const loc = useLocation();
  const navigate = useNavigate();
  const params = normalizeQuery(loc.search);
  if (kind && entityId) params.set(filterKey(kind), entityId);
  const query = params.toString();
  const { list: data, entity } = useLoaderData() as ListData;
  const revalidator = useRevalidator();
  const root = useScroll(true);
  const title = kind
    ? entity.data
      ? displayName(entity.data)
      : labels[kind]
    : params.get("q")
      ? "搜索结果"
      : "全部视频";
  function change(key: string, value: string) {
    const p = normalizeQuery(loc.search);
    if (value) p.set(key, value);
    else p.delete(key);
    p.delete("page");
    navigate(loc.pathname + (p.size ? "?" + p : ""));
  }
  return (
    <main ref={root} className="container" data-list-page="">
      {kind && (
        <nav className="back-row">
          <Link to={"/" + kind} onClick={(event) => {
            if (!event.button && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey && hasSessionBack(history.state, historyStart)) {
              event.preventDefault();
              navigate(-1);
            }
          }}>
            <Icon name="back" />
            返回
          </Link>
        </nav>
      )}
      {!kind && !params.get("q") && (
        <ActorStrip selected={params.get("actor") || ""} search={query} />
      )}
      <div className="list-heading">
        <div className="heading-line">
          {kind === "actors" && entity.data && (
            <Avatar entity={entity.data} large />
          )}
          <div>
            <h1
              className={kind === "actors" ? "actor-name-title" : undefined}
              title={
                kind === "actors" && entity.data
                  ? nameHint(entity.data)
                  : undefined
              }
            >
              {title}
            </h1>
            <p className="muted">
              {data.data ? `${data.data.total} 个视频` : "正在读取视频"}
              {params.get("q") ? ` · “${params.get("q")}”` : ""}
            </p>
          </div>
        </div>
        <SortPicker
          value={params.get("sort") || "newest"}
          onChange={(value) => change("sort", value)}
        />
      </div>
      {kind && (
        <div className="filters">
          <FacetStrip
            key={kind}
            kind={kind}
            value={params.get(filterKey(kind)) || ""}
            onChange={(v) =>
              navigate(
                facetLink(
                  loc.search,
                  filterKey(kind),
                  v,
                  entityId ? { kind, id: entityId } : undefined,
                ),
              )
            }
          />
        </div>
      )}
      {entity.error ? (
        <Message title="分类未取得">
          {entity.error}
          <Link to="/">返回全部视频</Link>
        </Message>
      ) : data.error ? (
        <Message
          title="列表暂未取得"
          action={
            <button onClick={() => revalidator.revalidate()}>重试</button>
          }
        >
          {data.error}
        </Message>
      ) : !data.data?.items.length ? (
        <Message
          title="没有符合条件的视频"
          action={<Link to="/">浏览全部视频</Link>}
        >
          试试减少筛选条件或更换关键词。
        </Message>
      ) : (
        <>
          <VideoGrid items={data.data.items} />
          <Pages page={data.data.page} pages={data.data.pages} />
        </>
      )}
    </main>
  );
}
// Read the existing router synchronously, including a navigation not rendered by React yet.
function categoryPendingLocation() { return router.state.navigation.location; }
function Directory({ kind }: { kind: Kind }) {
  const loc = useLocation(),
    navigate = useNavigate();
  const params = normalizeQuery(loc.search);
  const data = useLoaderData() as DirectoryData;
  useCategoryPagination(kind, data, categoryPendingLocation);
  const revalidator = useRevalidator();
  const root = useScroll(true);
  const [text, setText] = useState(params.get("q") || "");
  useEffect(() => setText(params.get("q") || ""), [loc.search]);
  return (
    <main ref={root} className="container directory" data-directory={kind}>
      <div className="list-heading">
        <div>
          <h1>{labels[kind]}目录</h1>
          <p className="muted">
            {data.data?.total ?? "…"} 个{labels[kind]}
          </p>
        </div>
        <form
          className="directory-search"
          onSubmit={(e) => {
            e.preventDefault();
            navigate(
              "/" +
                kind +
                (text ? "?q=" + encodeURIComponent(text.slice(0, 200)) : ""),
            );
          }}
        >
          <input
            aria-label={"搜索" + labels[kind]}
            placeholder={"搜索" + labels[kind]}
            value={text}
            maxLength={200}
            onChange={(e) => setText(e.target.value)}
          />
          <button>搜索</button>
        </form>
      </div>
      {data.error ? (
        <Message
          title="目录未取得"
          action={
            <button onClick={() => revalidator.revalidate()}>重试</button>
          }
        >
          {data.error}
        </Message>
      ) : !data.data?.items.length ? (
        <Message title="没有匹配结果" />
      ) : (
        <>
          <div className={"entity-grid " + kind}>
            {data.data.items.map((e) => (
              <Link
                key={e.id}
                to={`/${kind}/${e.id}`}
                className="entity-card"
                data-entity-id={e.id}
                title={nameHint(e)}
              >
                {kind === "actors" ? (
                  <Avatar entity={e} large />
                ) : (
                  <span className="entity-symbol">
                    <Icon name={kind === "studios" ? "studio" : "tag"} />
                  </span>
                )}
                <strong>{displayName(e)}</strong>
                <span className="muted">{e.count} 个视频</span>
              </Link>
            ))}
          </div>
          <Pages page={data.data.page} pages={data.data.pages} />
        </>
      )}
    </main>
  );
}
function EntityRoute({ kind }: { kind: Kind }) {
  const { id = "" } = useParams();
  return <VideoList kind={kind} entityId={id} />;
}
function Watch() {
  const { cid = "", mid = "" } = useParams();
  const loc = useLocation(),
    navigate = useNavigate();
  const valid = validWatch(cid, mid);
  const resumeId = new URLSearchParams(loc.search).get('resume') || '';
  const restore = useData<Resume>(/^[0-9a-f]{32}$/.test(resumeId) ? `/api/history/${resumeId}/resume` : null);
  const data = useData<Video>(valid ? `/api/videos/${cid}/${mid}` : null);
  // 同组换段时沿用已取得的组数据，播放器与video节点不卸载；换到其他作品才重新加载。
  const [kept, setKept] = useState<Video | null>(null);
  useEffect(() => {
    if (data.data) setKept(data.data);
  }, [data.data]);
  const video =
    data.data ||
    (!data.error && kept?.group && partIndex(kept.group, cid, mid) >= 0
      ? kept
      : undefined);
  const group = video?.group;
  const found = group ? partIndex(group, cid, mid) : -1;
  const index = group ? (found >= 0 ? found : group.index) : 0;
  const lead = group?.parts[0];
  const related = useData<{ items: Video[]; basis: string }>(
    lead ? `/api/videos/${lead.channel_id}/${lead.message_id}/related` : null,
  );
  const root = useScroll(true, true);
  const from = safeReturn(loc.state?.from);
  const toSegment = useCallback(
    (position: number) => {
      const p = group?.parts[position];
      if (p)
        navigate(`/watch/${p.channel_id}/${p.message_id}`, {
          replace: true,
          state: segmentState(loc.state),
        });
    },
    [group, navigate, loc.state],
  );
  const restoring = !!resumeId && restore.loading;
  const verifiedRestore = restore.data && restore.data.account_id === currentSession()?.id && restore.data.work_id === group?.id ? restore.data : undefined;
  useEffect(() => {
    if (!verifiedRestore) return;
    if (String(verifiedRestore.channel_id) !== cid || String(verifiedRestore.message_id) !== mid) {
      navigate(`/watch/${verifiedRestore.channel_id}/${verifiedRestore.message_id}?resume=${resumeId}`, {replace:true,state:loc.state});
    }
  }, [verifiedRestore,cid,mid,resumeId,navigate,loc.state]);
  const restoreRedirect = verifiedRestore && (String(verifiedRestore.channel_id) !== cid || String(verifiedRestore.message_id) !== mid);
  function back(event: React.MouseEvent<HTMLAnchorElement>) {
    if (
      event.button ||
      event.ctrlKey ||
      event.metaKey ||
      event.shiftKey ||
      event.altKey
    )
      return;
    if (loc.state?.from && history.state?.idx > 0) {
      event.preventDefault();
      navigate(-1);
    }
  }
  const multi = !!group && group.parts.length > 1;
  const current = multi ? group.parts[index] : null;
  const title = video ? displayTitle(video) : "";
  const code = video?.code?.trim() || "";
  const titleTranslationLabel = video ? translationLabel(video.title_translation) : "";
  return (
    <main ref={root} className="container watch" data-watch-page="">
      <nav className="back-row">
        <Link to={from} onClick={back}>
          <Icon name="back" />
          返回
        </Link>
      </nav>
      {!valid ? (
        <Message title="观看地址无效" />
      ) : restoring || restoreRedirect ? <Loading /> : video && group ? (
        <>
          {multi || video.available ? (
            <Player
              key={group.id}
              video={video}
              group={group}
              index={index}
              onSegment={toSegment}
              restore={verifiedRestore}
            />
          ) : (
            <Message title="视频不可用">
              原消息已删除或当前账号无权限，现有资料保留供查看。
            </Message>
          )}
          {resumeId && (restore.error || (!restoring && !verifiedRestore)) && <p className="player-notice">历史位置未取得，已按普通入口打开。</p>}
          {verifiedRestore?.note && <p className="player-notice">{verifiedRestore.note}</p>}
          <section className="watch-info" data-watch-info="">
            <h1 data-display-title="">
              {code && title.startsWith(code) ? (
                <>
                  <span className="watch-code">{code}</span>
                  {title.slice(code.length)}
                </>
              ) : (
                title
              )}
            </h1>
            {!["machine", "dictionary"].includes(
              video.title_translation?.method || "",
            ) && titleTranslationLabel && (
              <p className="muted" data-translation-label="">
                {titleTranslationLabel}
              </p>
            )}
            <details className="original" data-original-title="">
              <summary>查看原片名</summary>
              <p>{video.title}</p>
            </details>
            <dl className="metadata">
              {KINDS.map((kind) => (
                <div key={kind}>
                  <dt>{labels[kind]}</dt>
                  <dd>
                    {video.entities[kind].length
                      ? video.entities[kind].map((e, i) => (
                          <Fragment key={e.id}>
                            {i ? " · " : ""}
                            <Link to={`/${kind}/${e.id}`} title={nameHint(e)}>
                              {displayName(e)}
                            </Link>
                          </Fragment>
                        ))
                      : "未取得"}
                  </dd>
                </div>
              ))}
              <div>
                <dt>发行日期</dt>
                <dd>{video.release_date || "未取得"}</dd>
              </div>
              <div>
                <dt>上传日期</dt>
                <dd>{video.uploaded_at.slice(0, 10)}</dd>
              </div>
            </dl>
            <div className="source-links" aria-label="相关链接">
              {safeLink(current ? current.message_url : video.message_url) && (
                <a
                  href={
                    safeLink(current ? current.message_url : video.message_url)!
                  }
                  target="_blank"
                  rel="noopener noreferrer"
                  referrerPolicy="no-referrer"
                >
                  {multi
                    ? `第${index + 1}段原 Telegram 消息 ↗`
                    : "原 Telegram 消息 ↗"}
                </a>
              )}
              {video.sources?.map((s, i) =>
                safeLink(s.url) ? (
                  <a
                    key={i}
                    href={safeLink(s.url)!}
                    target="_blank"
                    rel="noopener noreferrer"
                    referrerPolicy="no-referrer"
                  >
                    {s.name} ↗
                  </a>
                ) : (
                  <span key={i}>{s.name}</span>
                ),
              )}
            </div>
          </section>
          <section className="related" aria-label="相关推荐">
            <div className="section-title">
              <h2>相关推荐</h2>
            </div>
            {related.loading ? (
              <Loading />
            ) : related.error ? (
              <Message title="相关推荐未取得" />
            ) : (
              <VideoGrid items={related.data?.items ?? []} />
            )}
          </section>
        </>
      ) : data.loading ? (
        <div className="player-skeleton skeleton" />
      ) : data.error ? (
        <Message title="视频未取得" action={<Link to="/">返回全部视频</Link>}>
          {data.error}
        </Message>
      ) : null}
    </main>
  );
}
/** Only the initial load needs a page fallback; navigation retains the current page. */
function InitialPage() {
  const loc = useLocation();
  const directory = KINDS.some((kind) => loc.pathname === "/" + kind);
  return (
    <main
      className={"container" + (directory ? " directory" : "")}
      aria-busy="true"
    >
      <Loading />
    </main>
  );
}
function Layout() {
  useEffect(() => {
    const check = () => { sessionCheck().catch(() => {}); };
    const timer = window.setInterval(check, 5000);
    window.addEventListener("focus", check);
    return () => { window.clearInterval(timer); window.removeEventListener("focus", check); };
  }, []);
  return (
    <>
      <Header />
      <Outlet />
    </>
  );
}
let router: ReturnType<typeof createBrowserRouter>;
function renderApp() {
router = createBrowserRouter([
  { path: "/login", element: <Login /> },
  {
    element: <Layout />,
    children: [
      { path: "/history", element: <History /> },
      { path: "/admin/accounts", element: <Accounts /> },
      {
        path: "/",
        loader: (args: Parameters<typeof loadVideoList>[0]) =>
          loadVideoList(args),
        element: <VideoList />,
        hydrateFallbackElement: <InitialPage />,
      },
      ...KINDS.flatMap((kind) => [
        {
          path: "/" + kind,
          loader: (args: Parameters<typeof loadDirectory>[0]) =>
            loadDirectory(args, kind),
          element: <Directory kind={kind} />,
          hydrateFallbackElement: <InitialPage />,
        },
        {
          path: "/" + kind + "/:id",
          loader: (args: Parameters<typeof loadVideoList>[0]) =>
            loadVideoList(args, kind),
          element: <EntityRoute kind={kind} />,
          hydrateFallbackElement: <InitialPage />,
        },
      ]),
      // Keep Watch's stable-video, same-group segment and source-release behavior unchanged.
      { path: "/watch/:cid/:mid", element: <Watch /> },
      {
        path: "*",
        element: (
          <main className="container">
            <Message
              title="页面不存在"
              action={<Link to="/">返回全部视频</Link>}
            />
          </main>
        ),
      },
    ],
  },
]);
createRoot(document.getElementById("root")!).render(
  <RouterProvider router={router} />,
);

}
// No protected component is mounted before the server has validated the cookie.
if (window.location.pathname === "/login") renderApp();
else sessionCheck().then(person => { if (person) renderApp(); }).catch(() => {
  createRoot(document.getElementById("root")!).render(<main className="login-shell"><section className="account-panel"><h1>登录状态未取得</h1><p className="muted">请检查连接后刷新重试。</p><button onClick={() => window.location.reload()}>重试</button></section></main>);
});
