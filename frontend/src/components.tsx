import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import { displayName, displayTitle, titleHint } from "./display";
import { jumpPage, pageHref } from "./pagination";
import type { Entity, Video } from "./types";

const stateLabels: Record<string, string> = {
  matched: "资料完整",
  partial: "部分资料",
  unidentified: "未识别番号",
  ambiguous: "番号待核对",
  temporary_error: "部分信息未取得",
  unsupported: "暂无适用资料",
  pending: "资料待补齐",
  processing: "资料补齐中",
};
export const BRAND_ICON = "/assets/sefang-icon-836f1222d7b86f34.svg";
export const BRAND_WORDMARK = "/assets/sefang-wordmark-b563570aba759b24.svg";
type IconName =
  | "search"
  | "arrow"
  | "back"
  | "tag"
  | "studio"
  | "play"
  | "close"
  | "chevron"
  | "prev"
  | "next"
  | "external"
  | "history"
  | "user"
  | "logout"
  | "image"
  | "alert";
// One 24px grid, 1.7 stroke, round joins: every interface glyph shares the same weight.
const paths: Record<IconName, string> = {
  search: "M20 20l-4.2-4.2M18 10.5a7.5 7.5 0 1 1-15 0 7.5 7.5 0 0 1 15 0",
  arrow: "M5 12h14M13 6l6 6-6 6",
  back: "m14 6-6 6 6 6",
  tag: "M20 13 13 20a2 2 0 0 1-3 0L2 12V3h9l9 8a1.4 1.4 0 0 1 0 2M7 7h.01",
  studio: "M4 9h16v12H4zM3 3h18v6H3zM8 3l-3 6M14 3l-3 6M20 3l-3 6",
  play: "m9 5 11 7-11 7z",
  close: "M7 7l10 10M17 7 7 17",
  chevron: "m9 6 6 6-6 6",
  prev: "m15 6-6 6 6 6",
  next: "m9 6 6 6-6 6",
  external: "M14 4h6v6M20 4l-9 9M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4",
  history: "M3.5 12a8.5 8.5 0 1 0 2.5-6M3 4v4h4M12 8v4.5l3 2",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8M4.5 20a7.5 7.5 0 0 1 15 0",
  logout: "M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4M10 16l-4-4 4-4M6 12h10",
  image: "M4 6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2zM4 16l4.5-4.5a1.5 1.5 0 0 1 2 0L16 17M14 13l1.5-1.5a1.5 1.5 0 0 1 2 0L20 14M15 8.5h.01",
  alert: "M12 8v5M12 16.5h.01M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18",
};
export function Icon({ name }: { name: IconName }) {
  return (
    <svg
      className="ui-icon"
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name]} />
    </svg>
  );
}
/** Code-first titles: the canonical number is the only coloured part of any title. */
export function CodeTitle({ title, code }: { title: string; code?: string }) {
  const value = code?.trim() || "";
  return value && title.startsWith(value) ? (
    <>
      <span className="watch-code">{value}</span>
      {title.slice(value.length)}
    </>
  ) : (
    <>{title}</>
  );
}
/** Empty and failure states share one quiet mark: the brand's own hand-written 涩, desaturated. */
export function MessageMark() {
  return <img className="message-mark" src={BRAND_ICON} alt="" aria-hidden="true" width={40} height={40} />;
}
export function Message({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="message" role="status">
      <MessageMark />
      <strong>{title}</strong>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}
/** Skeletons mirror the real layout they stand in for, so the page never jumps on arrival. */
export function Loading({ count = 12, variant = "videos" }: { count?: number; variant?: "videos" | "tiles" | "rows" }) {
  return (
    <div className={"skeleton-grid" + (variant === "videos" ? "" : " skeleton-" + variant)} aria-label="正在读取视频">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="skeleton-card" aria-hidden="true">
          <div className="skeleton skeleton-art" />
          <div className="skeleton skeleton-line" />
          <div className="skeleton skeleton-line short" />
        </div>
      ))}
    </div>
  );
}
export function Avatar({
  entity,
  large = false,
}: {
  entity: Entity;
  large?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  return (
    <span className={"avatar" + (large ? " large" : "")}>
      {entity.avatar && !failed ? (
        <img
          src={entity.avatar}
          alt=""
          loading="lazy"
          onError={() => setFailed(true)}
        />
      ) : (
        <span aria-label="头像未取得">{entity.name.slice(0, 1)}</span>
      )}
    </span>
  );
}
function Artwork({ video }: { video: Video }) {
  const [src, setSrc] = useState(video.cover);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    setSrc(video.cover);
    setFailed(false);
  }, [video.id, video.cover]);
  function fallback() {
    if (src.endsWith("/cover"))
      setSrc(
        `/api/videos/${video.channel_id}/${video.message_id}/thumbnail?skip_cover=true`,
      );
    else setFailed(true);
  }
  return (
    <div className="art">
      {failed ? (
        <div className="art-placeholder" data-missing-cover="">
          <Icon name="image" />
          <small>暂无封面</small>
        </div>
      ) : (
        <img src={src} alt="" loading="lazy" onError={fallback} />
      )}
    </div>
  );
}
function Card({ video }: { video: Video }) {
  const loc = useLocation();
  const title = displayTitle(video);
  const cast = video.entities.actors.map(displayName).join(" · ");
  return (
    <article className="card" data-video-id={video.id}>
      <Link
        className="card-link"
        to={`/watch/${video.channel_id}/${video.message_id}`}
        state={{ from: loc.pathname + loc.search }}
        aria-label={`观看 ${title}`}
      >
        <Artwork video={video} />
        <h3
          title={titleHint(video)}
          data-title-translation={video.title_translation?.state}
        >
          <CodeTitle title={title} code={video.code} />
        </h3>
      </Link>
      <div className="card-meta">
        <span className={"card-cast" + (cast ? "" : " is-state")} title={cast}>
          {cast || stateLabels[video.state] || "资料未取得"}
        </span>
        <span className="card-date">{video.release_date || "日期未知"}</span>
      </div>
    </article>
  );
}
export function VideoGrid({ items }: { items: Video[] }) {
  return (
    <div className="video-grid">
      {items.map((video) => (
        <Card key={video.id} video={video} />
      ))}
    </div>
  );
}
export function Pages({ page, pages }: { page: number; pages: number }) {
  const loc = useLocation(),
    navigate = useNavigate();
  const [target, setTarget] = useState(String(page));
  useEffect(
    () => setTarget(String(page)),
    [page, pages, loc.pathname, loc.search],
  );
  const href = (p: number) => pageHref(loc.pathname, loc.search, p);
  function jump(event: FormEvent) {
    event.preventDefault();
    const next = jumpPage(target, pages);
    if (next === null) return;
    setTarget(String(next));
    if (next !== page) navigate(href(next));
  }
  if (pages <= 1) return null;
  return (
    <nav className="pagination" aria-label="视频分页">
      {page > 1 ? (
        <Link className="page-step" rel="prev" to={href(page - 1)}>
          <Icon name="prev" />
          上一页
        </Link>
      ) : (
        <span className="page-step" aria-disabled="true">
          <Icon name="prev" />
          上一页
        </span>
      )}
      <span className="page-status">
        第 <b>{page}</b> / {pages} 页
      </span>
      {page < pages ? (
        <Link className="page-step next" rel="next" to={href(page + 1)}>
          下一页
          <Icon name="next" />
        </Link>
      ) : (
        <span className="page-step next" aria-disabled="true">
          下一页
          <Icon name="next" />
        </span>
      )}
      <form className="page-jump" onSubmit={jump}>
        <input
          aria-label="跳转页码"
          inputMode="numeric"
          autoComplete="off"
          enterKeyHint="go"
          value={target}
          onChange={(event) => setTarget(event.target.value)}
        />
        <button type="submit">跳转</button>
      </form>
    </nav>
  );
}
