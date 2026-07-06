import { useEffect, useRef, useState } from "react";
import {
  cancelJob,
  getJob,
  isActive,
  Job,
  ProgressEvent,
  Subscribe,
  subscribeJobEvents,
  Track,
} from "../lib/api";
import TrackRow from "./TrackRow";

const STATE_STYLE: Record<string, string> = {
  queued: "bg-slate-700 text-slate-200",
  resolving: "bg-sky-800 text-sky-100",
  running: "bg-emerald-800 text-emerald-100",
  done: "bg-emerald-500 text-slate-950",
  failed: "bg-red-600 text-white",
  cancelled: "bg-amber-700 text-amber-100",
};

interface LiveTrack {
  title: string;
  pct: number;
  speed?: string;
}

export interface JobCardProps {
  job: Job;
  onChanged?: () => void;
  subscribe?: Subscribe;
}

export default function JobCard({ job, onChanged, subscribe = subscribeJobEvents }: JobCardProps) {
  const [live, setLive] = useState(job);
  const [downloading, setDownloading] = useState<Map<string, LiveTrack>>(new Map());
  const [tracks, setTracks] = useState<Track[] | null>(null);
  const [expanded, setExpanded] = useState(false);
  const counters = useRef({ completed: job.completed, failed: job.failed });

  useEffect(() => {
    setLive(job);
    counters.current = { completed: job.completed, failed: job.failed };
  }, [job]);

  useEffect(() => {
    if (!isActive(job.state)) return;
    const unsubscribe = subscribe(job.id, (event: ProgressEvent) => {
      if (event.event === "state") {
        setLive((prev) => ({
          ...prev,
          state: event.state ?? prev.state,
          total: event.total ?? prev.total,
        }));
      } else if (event.event === "progress") {
        const key = event.external_id ?? String(event.track_id ?? "");
        setDownloading((prev) => {
          const next = new Map(prev);
          next.set(key, {
            title: event.title ?? key,
            pct: event.pct ?? 0,
            speed: event.speed,
          });
          return next;
        });
      } else if (event.event === "track_done") {
        const key = event.external_id ?? String(event.track_id ?? "");
        if (event.status === "failed") counters.current.failed += 1;
        else counters.current.completed += 1;
        setDownloading((prev) => {
          const next = new Map(prev);
          next.delete(key);
          return next;
        });
        setLive((prev) => ({
          ...prev,
          completed: counters.current.completed,
          failed: counters.current.failed,
        }));
      } else if (event.event === "job_done") {
        setLive((prev) => ({ ...prev, state: event.state ?? "done" }));
        setDownloading(new Map());
        onChanged?.();
      }
    });
    return unsubscribe;
  }, [job.id, job.state, subscribe, onChanged]);

  const toggleExpand = async () => {
    const next = !expanded;
    setExpanded(next);
    if (next && tracks === null) {
      try {
        setTracks((await getJob(job.id)).tracks);
      } catch {
        setTracks([]);
      }
    }
  };

  const total = Math.max(live.total, 1);
  const pct = Math.min(100, ((live.completed + live.failed) / total) * 100);

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex items-center gap-3">
        <span
          data-testid="job-state"
          className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${STATE_STYLE[live.state] ?? ""}`}
        >
          {live.state}
        </span>
        <span className="min-w-0 flex-1 truncate text-sm text-slate-300" title={live.url}>
          {live.url}
        </span>
        <span className="text-xs tabular-nums text-slate-400">
          {live.completed + live.failed}/{live.total || "?"}
        </span>
        {isActive(live.state) && (
          <button
            onClick={() => void cancelJob(job.id).then(() => onChanged?.())}
            className="rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:border-red-500 hover:text-red-300"
          >
            Cancel
          </button>
        )}
        <button
          onClick={() => void toggleExpand()}
          className="rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:border-emerald-500"
        >
          {expanded ? "Hide" : "Tracks"}
        </button>
      </div>

      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-800">
        <div
          className="h-full rounded-full bg-emerald-500 transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>

      {downloading.size > 0 && (
        <ul className="mt-3 space-y-1.5">
          {[...downloading.entries()].map(([key, t]) => (
            <li key={key} className="flex items-center gap-2 text-xs text-slate-400">
              <span className="min-w-0 flex-1 truncate">{t.title}</span>
              {t.speed && <span className="text-slate-500">{t.speed}</span>}
              <div className="h-1 w-24 overflow-hidden rounded-full bg-slate-800">
                <div className="h-full bg-sky-500" style={{ width: `${t.pct}%` }} />
              </div>
              <span className="w-10 text-right tabular-nums">{t.pct.toFixed(0)}%</span>
            </li>
          ))}
        </ul>
      )}

      {expanded && tracks !== null && (
        <div className="mt-3 divide-y divide-slate-800 border-t border-slate-800">
          {tracks.length === 0 ? (
            <p className="py-3 text-xs text-slate-500">No tracks recorded for this job yet.</p>
          ) : (
            tracks.map((t) => <TrackRow key={t.id} track={t} onChanged={onChanged} />)
          )}
        </div>
      )}
    </div>
  );
}
