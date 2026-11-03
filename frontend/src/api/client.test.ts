/**
 * API client tests — Phase 7.
 *
 * Verifies request construction, auth header injection, and error handling.
 * Uses a mock fetch since we're testing the client logic, not the network.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, clearToken, setToken } from "./client";

// Mock fetch
const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

describe("api client", () => {
  beforeEach(() => {
    sessionStorage.clear();
    mockFetch.mockReset();
  });

  afterEach(() => {
    clearToken();
  });

  it("attaches Authorization header when token is set", async () => {
    setToken("my-jwt");
    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ data: "ok" }),
      headers: new Headers({ "content-type": "application/json" }),
    });

    await api("/test");

    const [, opts] = mockFetch.mock.calls[0];
    expect(opts.headers["Authorization"]).toBe("Bearer my-jwt");
  });

  it("skips Authorization when skipAuth is true", async () => {
    setToken("my-jwt");
    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({}),
      headers: new Headers(),
    });

    await api("/test", { skipAuth: true });

    const [, opts] = mockFetch.mock.calls[0];
    expect(opts.headers["Authorization"]).toBeUndefined();
  });

  it("throws ApiError with status on non-ok response", async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 403,
      json: () => Promise.resolve({ detail: "forbidden" }),
      headers: new Headers(),
    });

    await expect(api("/test")).rejects.toThrow(ApiError);
    try {
      await api("/test");
    } catch (e) {
      expect((e as ApiError).status).toBe(403);
      expect((e as ApiError).message).toBe("forbidden");
    }
  });

  it("sends JSON body for POST requests", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      status: 201,
      json: () => Promise.resolve({ id: "123" }),
      headers: new Headers(),
    });

    await api("/test", { method: "POST", body: { name: "test" }, skipAuth: true });

    const [, opts] = mockFetch.mock.calls[0];
    expect(opts.method).toBe("POST");
    expect(JSON.parse(opts.body)).toEqual({ name: "test" });
  });

  it("calls the correct URL with api prefix", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({}),
      headers: new Headers(),
    });

    await api("/languages", { skipAuth: true });

    const [url] = mockFetch.mock.calls[0];
    expect(url).toContain("/api/v1/languages");
  });
});
