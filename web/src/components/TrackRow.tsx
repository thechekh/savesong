import { useState } from "react";
import { retryTrack, Track } from "../lib/api";

const STATUS_COLOR: Record<string, string> = {
  done: "text-emerald-400",
  failed: "text-red-400",
  needs_review: "text-amber-400",
  downloading: "text-sky-400",
  skipped: "text-slate-500",
};

export default function TrackRow({
  track,
  onChanged,
}: {
  track: Track;
  onChanged?: () => void;
}) {
  const [retried, setRetried] = useState(false);

  const retry = async () => {
    await retryTrack(track.id);
    setRetried(true);
    onChanged?.();
  };

  return (
    <div className="flex items-center gap-3 py-2 text-sm">
      <span className={`w-24 shrink-0 text-xs ${STATUS_COLOR[track.status] ?? "text-slate-400"}`}>
        {track.status.replace("_", " ")}
      </span>
      <span className="min-w-0 flex-1 truncate">
        <span className="text-slate-400">{track.artists.join(", ")}</span>
        <span className="mx-1.5 text-slate-600">·</span>
        {track.title}
      </span>
      {track.match_score != null && (
        <span className="text-xs tabular-nums text-slate-500">
          {track.match_score.toFixed(2)}
        </span>
      )}
      {track.error && (
        <span className="max-w-48 truncate text-xs text-red-400" title={track.error}>
          {track.error}
        </span>
      )}
      {track.status === "failed" && !retried && (
        <button
          onClick={() => void retry()}
          className="rounded-md border border-slate-700 px-2 py-0.5 text-xs text-slate-300 hover:border-emerald-500"
        >
          Retry
        </button>
      )}
      {retried && <span className="text-xs text-sky-400">queued</span>}
    </div>
  );
}
