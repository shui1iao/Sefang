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
type IconName = "search" | "arrow" | "back" | "tag" | "studio" | "play";
const paths: Record<IconName, string> = {
  search: "M21 21l-4.4-4.4M19 10.5a8.5 8.5 0 1 1-17 0 8.5 8.5 0 0 1 17 0",
  arrow: "M7 17 17 7M7 7h10v10",
  back: "m14 6-6 6 6 6",
  tag: "M20 13 13 20a2 2 0 0 1-3 0L2 12V3h9l9 8a1.4 1.4 0 0 1 0 2M7 7h.01",
  studio: "M4 9h16v12H4zM3 3h18v6H3zM8 3l-3 6M14 3l-3 6M20 3l-3 6",
  play: "m9 5 11 7-11 7z",
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
      <span className="message-mark" aria-hidden="true">
        ◌
      </span>
      <strong>{title}</strong>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}
export function Loading() {
  return (
    <div className="skeleton-grid" aria-label="正在读取视频">
      {Array.from({ length: 12 }, (_, i) => (
        <div key={i} className="skeleton" />
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
          <span className="art-placeholder-mark">
            <Icon name="play" />
          </span>
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
          {title}
        </h3>
      </Link>
      <div className="card-meta">
        <span className="card-cast" title={cast}>
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
        <Link to={href(page - 1)} rel="prev">
          上一页
        </Link>
      ) : (
        <span aria-disabled="true">上一页</span>
      )}
      <span>
        第 <b>{page}</b> / {pages} 页
      </span>
      {page < pages ? (
        <Link to={href(page + 1)} rel="next">
          下一页
        </Link>
      ) : (
        <span aria-disabled="true">下一页</span>
      )}
      <form className="page-jump" onSubmit={jump}>
        <input
          aria-label="跳转页码"
          inputMode="numeric"
          autoComplete="off"
          value={target}
          onChange={(event) => setTarget(event.target.value)}
        />
        <button type="submit">跳转</button>
      </form>
    </nav>
  );
}
