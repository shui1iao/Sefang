import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useLocation, useNavigationType } from "react-router";
import { readJson } from "./data";

export function useData<T>(url: string | null) {
  const [state, setState] = useState<{
    url: string | null;
    data?: T;
    error?: string;
  }>({ url: null });
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (!url) return;
    const control = new AbortController();
    setState({ url });
    readJson<T>(url, control.signal)
      .then((data) => {
        if (!control.signal.aborted) setState({ url, data });
      })
      .catch((error) => {
        if (!control.signal.aborted) setState({ url, error: error.message });
      });
    return () => control.abort();
  }, [url, revision]);
  const current = state.url === url ? state : { url };
  return {
    ...current,
    loading: !!url && !current.data && !current.error,
    retry: () => setRevision((v) => v + 1),
  };
}
function scrollHost(node: HTMLElement | null) {
  for (
    let p = node?.parentElement;
    p && p !== document.body;
    p = p.parentElement
  )
    if (
      /auto|scroll/.test(getComputedStyle(p).overflowY) &&
      p.scrollHeight > p.clientHeight
    )
      return p;
  return document.scrollingElement as HTMLElement;
}
export function useScroll(ready: boolean, watch = false) {
  const location = useLocation();
  const action = useNavigationType();
  const root = useRef<HTMLElement>(null);
  const restoreDone = useRef(false);
  useLayoutEffect(() => {
    restoreDone.current = false;
    history.scrollRestoration = "manual";
    const key = "se-scroll:" + location.key;
    const save = () => {
      if (restoreDone.current)
        sessionStorage.setItem(key, String(scrollHost(root.current).scrollTop));
    };
    window.addEventListener("scroll", save, { passive: true });
    window.addEventListener("pagehide", save);
    return () => {
      window.removeEventListener("scroll", save);
      window.removeEventListener("pagehide", save);
    };
  }, [location.key]);
  useLayoutEffect(() => {
    if (!ready || restoreDone.current) return;
    if (watch && (location.state as { segment?: boolean } | null)?.segment) {
      restoreDone.current = true;
      return;
    }
    let gone = false,
      frame = 0,
      times = 0;
    const saved = Number(
      sessionStorage.getItem("se-scroll:" + location.key) || 0,
    );
    const top =
      !watch && action === "POP" && Number.isFinite(saved)
        ? Math.min(saved, 10000000)
        : 0;
    const restore = () => {
      if (gone) return;
      scrollHost(root.current).scrollTop = top;
      if (++times < 4) frame = requestAnimationFrame(restore);
      else restoreDone.current = true;
    };
    frame = requestAnimationFrame(restore);
    return () => {
      gone = true;
      cancelAnimationFrame(frame);
    };
  }, [ready, location.key, location.state, action, watch]);
  return root;
}
