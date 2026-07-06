import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, createJob, fetchLibrary, listJobs, retryTrack } from "./api";

function mockFetch(status: number, body: unknown) {
  // a fresh Response per call — bodies are single-read
  const fn = vi.fn().mockImplementation(() =>
    Promise.resolve(
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("api client", () => {
  it("posts new jobs with url and format", async () => {
    const fn = mockFetch(202, { job_id: "abc123" });
    const result = await createJob("https://soundcloud.com/a/sets/b", "opus");
    expect(result.job_id).toBe("abc123");
    const [path, init] = fn.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/api/jobs");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      url: "https://soundcloud.com/a/sets/b",
      format: "opus",
    });
  });

  it("lists jobs", async () => {
    const fn = mockFetch(200, []);
    await listJobs();
    expect(fn.mock.calls[0][0]).toBe("/api/jobs");
  });

  it("builds library query strings", async () => {
    const fn = mockFetch(200, { items: [], next_cursor: null });
    await fetchLibrary(42, "daft punk");
    expect(fn.mock.calls[0][0]).toBe("/api/library?cursor=42&q=daft+punk");
    await fetchLibrary();
    expect(fn.mock.calls[1][0]).toBe("/api/library");
  });

  it("posts track retries", async () => {
    const fn = mockFetch(202, { status: "queued" });
    await retryTrack(7);
    expect(fn.mock.calls[0][0]).toBe("/api/tracks/7/retry");
  });

  it("raises ApiError with status on failure", async () => {
    mockFetch(422, { code: "unsupported_url" });
    await expect(createJob("https://example.com", "opus")).rejects.toThrowError(ApiError);
    await expect(createJob("https://example.com", "opus")).rejects.toMatchObject({
      status: 422,
    });
  });
});
