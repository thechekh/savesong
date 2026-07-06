import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Job, ProgressEvent } from "../lib/api";
import JobCard from "./JobCard";

const baseJob: Job = {
  id: "job1",
  url: "https://soundcloud.com/dj-orbit/sets/late-night-mix",
  state: "running",
  total: 2,
  completed: 0,
  failed: 0,
  created_at: "2026-07-06T12:00:00+00:00",
};

function subscribeStub() {
  let handler: ((e: ProgressEvent) => void) | null = null;
  const unsubscribe = vi.fn();
  const subscribe = vi.fn((_: string, onEvent: (e: ProgressEvent) => void) => {
    handler = onEvent;
    return unsubscribe;
  });
  return {
    subscribe,
    unsubscribe,
    emit: (e: ProgressEvent) => act(() => handler?.(e)),
  };
}

describe("JobCard", () => {
  it("renders state, url, and counters", () => {
    const { subscribe } = subscribeStub();
    render(<JobCard job={baseJob} subscribe={subscribe} />);
    expect(screen.getByTestId("job-state")).toHaveTextContent("running");
    expect(screen.getByText(baseJob.url)).toBeInTheDocument();
    expect(screen.getByText("0/2")).toBeInTheDocument();
    expect(subscribe).toHaveBeenCalledWith("job1", expect.any(Function));
  });

  it("shows live per-track progress from SSE events", () => {
    const stub = subscribeStub();
    render(<JobCard job={baseJob} subscribe={stub.subscribe} />);

    stub.emit({ event: "progress", external_id: "t1", title: "First Wave", pct: 40, speed: "1.2 MB/s" });
    expect(screen.getByText("First Wave")).toBeInTheDocument();
    expect(screen.getByText("40%")).toBeInTheDocument();
    expect(screen.getByText("1.2 MB/s")).toBeInTheDocument();

    stub.emit({ event: "track_done", external_id: "t1", title: "First Wave", status: "done" });
    expect(screen.queryByText("40%")).not.toBeInTheDocument();
    expect(screen.getByText("1/2")).toBeInTheDocument();
  });

  it("flips to done on job_done and stops showing cancel", () => {
    const stub = subscribeStub();
    const onChanged = vi.fn();
    render(<JobCard job={baseJob} subscribe={stub.subscribe} onChanged={onChanged} />);
    expect(screen.getByText("Cancel")).toBeInTheDocument();

    stub.emit({ event: "job_done", state: "done" });
    expect(screen.getByTestId("job-state")).toHaveTextContent("done");
    expect(screen.queryByText("Cancel")).not.toBeInTheDocument();
    expect(onChanged).toHaveBeenCalled();
  });

  it("does not subscribe for finished jobs", () => {
    const { subscribe } = subscribeStub();
    render(<JobCard job={{ ...baseJob, state: "done" }} subscribe={subscribe} />);
    expect(subscribe).not.toHaveBeenCalled();
  });
});
