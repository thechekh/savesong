import { useCallback, useEffect, useState } from "react";
import { fetchLibrary, Track } from "../lib/api";

function Cover({ track }: { track: Track }) {
  if (track.cover_url) {
    return (
      <img
        src={track.cover_url}
        alt=""
        className="aspect-square w-full rounded-lg object-cover"
        loading="lazy"
      />
    );
  }
  return (
    <div className="flex aspect-square w-full items-center justify-center rounded-lg bg-gradient-to-br from-slate-800 to-slate-900 text-3xl text-slate-600">
      ♪
    </div>
  );
}

export default function Library() {
  const [items, setItems] = useState<Track[]>([]);
  const [cursor, setCursor] = useState<number | null>(null);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (query: string, after: number | null, append: boolean) => {
    setLoading(true);
    try {
      const page = await fetchLibrary(after, query || undefined);
      setItems((prev) => (append ? [...prev, ...page.items] : page.items));
      setCursor(page.next_cursor);
    } catch {
      if (!append) setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => void load(q, null, false), q ? 250 : 0);
    return () => clearTimeout(timer);
  }, [q, load]);

  return (
    <div className="space-y-6">
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Search title, artist, album…"
        className="w-full rounded-lg border border-slate-700 bg-slate-900 px-4 py-2.5 text-sm outline-none placeholder:text-slate-500 focus:border-emerald-500"
      />
      {items.length === 0 && !loading ? (
        <p className="py-16 text-center text-sm text-slate-500">
          {q ? "No matches in your library." : "Library is empty — download something first."}
        </p>
      ) : (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
          {items.map((track) => (
            <figure key={track.id} className="group">
              <Cover track={track} />
              <figcaption className="mt-2">
                <p className="truncate text-sm font-medium">{track.title}</p>
                <p className="truncate text-xs text-slate-400">{track.artists.join(", ")}</p>
                {track.album && (
                  <p className="truncate text-xs text-slate-600">{track.album}</p>
                )}
              </figcaption>
            </figure>
          ))}
        </div>
      )}
      {cursor !== null && (
        <div className="text-center">
          <button
            onClick={() => void load(q, cursor, true)}
            disabled={loading}
            className="rounded-lg border border-slate-700 px-6 py-2 text-sm text-slate-300 hover:border-emerald-500 disabled:opacity-40"
          >
            {loading ? "Loading…" : "Load more"}
          </button>
        </div>
      )}
    </div>
  );
}
