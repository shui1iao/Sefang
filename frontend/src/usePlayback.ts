import { useEffect, useState } from "react";
import { writeJson } from "./auth-client";

/** One server-issued handle for this stable video; not a login credential.
 * One window permits at most two bounded Range responses, all sharing account limits.
 */
export function usePlayback(group: string, channel: number, message: number) {
  const [id, setId] = useState(""), [error, fail] = useState(""), [version, renew] = useState(0);
  useEffect(() => {
    let alive = true, key = "";
    setId(""); fail("");
    const close = (value: string) => writeJson(`/api/playbacks/${value}/close`, {}).catch(() => {});
    writeJson<{ id: string }>("/api/playbacks", { channel_id: channel, message_id: message }).then(data => { key = data.id; if (alive) setId(key); else close(key); }, e => { if (alive) fail(e.message); });
    return () => { alive = false; if (key) close(key); };
  }, [version, group, channel, message]);
  return { id, error, renew: () => renew(v => v + 1) };
}
