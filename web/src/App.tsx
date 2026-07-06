import { useState } from "react";
import Library from "./pages/Library";
import Queue from "./pages/Queue";

type Tab = "queue" | "library";

export default function App() {
  const [tab, setTab] = useState<Tab>("queue");

  const tabClass = (active: boolean) =>
    `rounded-full px-4 py-1.5 text-sm font-medium transition-colors ${
      active ? "bg-emerald-500 text-slate-950" : "text-slate-300 hover:bg-slate-800"
    }`;

  return (
    <div className="mx-auto flex min-h-screen max-w-4xl flex-col px-4">
      <header className="flex items-center justify-between py-6">
        <h1 className="text-xl font-bold tracking-tight">
          <span className="text-emerald-400">Save</span>Song
        </h1>
        <nav className="flex gap-2 rounded-full bg-slate-900 p-1">
          <button className={tabClass(tab === "queue")} onClick={() => setTab("queue")}>
            Queue
          </button>
          <button className={tabClass(tab === "library")} onClick={() => setTab("library")}>
            Library
          </button>
        </nav>
      </header>
      <main className="flex-1 pb-16">{tab === "queue" ? <Queue /> : <Library />}</main>
      <footer className="border-t border-slate-800 py-4 text-center text-xs text-slate-500">
        For personal archiving of content you have rights to access.
      </footer>
    </div>
  );
}
