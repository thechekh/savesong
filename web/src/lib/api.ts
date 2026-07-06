// Typed client for the SaveSong API (see §2.6 of the spec).

export type JobState = "queued" | "resolving" | "running" | "done" | "failed" | "cancelled";
export type AudioFormat = "opus" | "m4a" | "mp3";

export interface Job {
  id: string;
  url: string;
  state: JobState;
  total: number;
  completed: number;
  failed: number;
  created_at: string;
  finished_at?: string | null;
}

export interface Track {
  id: number;
  title: string;
  artists: string[];
  album: string | null;
  status: string;
  match_score: number | null;
  error: string | null;
  cover_url: string | null;
  file_path: string | null;
  downloaded_at: string | null;
}

export interface JobDetail extends Job {
  tracks: Track[];
}

export interface LibraryPage {
  items: Track[];
  next_cursor: number | null;
}

export interface ProgressEvent {
  event: "state" | "progress" | "track_done" | "job_done";
  state?: JobState;
  total?: number;
  track_id?: number;
  external_id?: string;
  title?: string;
  pct?: number;
  speed?: string;
  status?: string;
  error?: string;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    body: string,
  ) {
    super(`API ${status}: ${body}`);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  return (await resp.json()) as T;
}

export const createJob = (url: string, format: AudioFormat) =>
  request<{ job_id: string }>("/api/jobs", {
    method: "POST",
    body: JSON.stringify({ url, format }),
  });

export const listJobs = () => request<Job[]>("/api/jobs");

export const getJob = (id: string) => request<JobDetail>(`/api/jobs/${id}`);

export const cancelJob = (id: string) =>
  request<{ status: string }>(`/api/jobs/${id}/cancel`, { method: "POST" });

export const retryTrack = (id: number) =>
  request<{ status: string }>(`/api/tracks/${id}/retry`, { method: "POST" });

export const fetchLibrary = (cursor?: number | null, q?: string) => {
  const params = new URLSearchParams();
  if (cursor != null) params.set("cursor", String(cursor));
  if (q) params.set("q", q);
  const suffix = params.size ? `?${params.toString()}` : "";
  return request<LibraryPage>(`/api/library${suffix}`);
};

export type Unsubscribe = () => void;
export type Subscribe = (jobId: string, onEvent: (e: ProgressEvent) => void) => Unsubscribe;

export const ACTIVE_STATES: JobState[] = ["queued", "resolving", "running"];

export const isActive = (state: JobState) => ACTIVE_STATES.includes(state);

export const subscribeJobEvents: Subscribe = (jobId, onEvent) => {
  const source = new EventSource(`/api/jobs/${jobId}/events`);
  const handler = (ev: MessageEvent) => {
    try {
      onEvent(JSON.parse(ev.data as string) as ProgressEvent);
    } catch {
      // malformed frame — ignore
    }
  };
  for (const name of ["state", "progress", "track_done", "job_done"]) {
    source.addEventListener(name, handler);
  }
  return () => source.close();
};
