import { FormEvent, useCallback, useEffect, useState } from "react";
import JobCard from "../components/JobCard";
import { ApiError, AudioFormat, createJob, Job, listJobs } from "../lib/api";

const POLL_MS = 4000;

export default function Queue() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [url, setUrl] = useState("");
  const [format, setFormat] = useState<AudioFormat>("opus");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setJobs(await listJobs());
    } catch {
      // API briefly unavailable — keep the last snapshot
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!url.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await createJob(url.trim(), format);
      setUrl("");
      await refresh();
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setError("That URL is not a supported Spotify / SoundCloud / YouTube Music link.");
      } else {
        setError("Could not queue the job — is the backend running?");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      <form onSubmit={submit} className="flex gap-2">
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="Paste a playlist or track URL (Spotify · SoundCloud · YT Music)"
          className="flex-1 rounded-lg border border-slate-700 bg-slate-900 px-4 py-2.5 text-sm outline-none placeholder:text-slate-500 focus:border-emerald-500"
        />
        <select
          value={format}
          onChange={(e) => setFormat(e.target.value as AudioFormat)}
          className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2.5 text-sm"
          aria-label="audio format"
        >
          <option value="opus">opus</option>
          <option value="m4a">m4a</option>
          <option value="mp3">mp3</option>
        </select>
        <button
          type="submit"
          disabled={submitting || !url.trim()}
          className="rounded-lg bg-emerald-500 px-5 py-2.5 text-sm font-semibold text-slate-950 transition-opacity disabled:opacity-40"
        >
          Download
        </button>
      </form>
      {error && (
        <p className="rounded-lg border border-red-900 bg-red-950/50 px-4 py-2 text-sm text-red-300">
          {error}
        </p>
      )}
      {jobs.length === 0 ? (
        <p className="py-16 text-center text-sm text-slate-500">
          No jobs yet — paste a URL above to start.
        </p>
      ) : (
        <div className="space-y-3">
          {jobs.map((job) => (
            <JobCard key={job.id} job={job} onChanged={() => void refresh()} />
          ))}
        </div>
      )}
    </div>
  );
}
