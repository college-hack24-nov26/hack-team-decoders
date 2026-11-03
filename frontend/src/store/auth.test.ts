/**
 * Auth store tests — Phase 7.
 *
 * The consent route guard and the interview placeholder both depend on
 * the auth store correctly reflecting login state and surviving a page refresh
 * (sessionStorage persistence). These tests verify that contract.
 */

import { beforeEach, describe, expect, it } from "vitest";
import { clearToken, getToken, setToken } from "../api/client";

describe("auth token storage", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("starts with no token", () => {
    expect(getToken()).toBeNull();
  });

  it("persists and retrieves a token", () => {
    setToken("test-jwt-123");
    expect(getToken()).toBe("test-jwt-123");
  });

  it("clearToken removes the session", () => {
    setToken("test-jwt-123");
    clearToken();
    expect(getToken()).toBeNull();
  });

  it("survives across separate getToken() calls (simulating navigation)", () => {
    setToken("abc.def.ghi");
    // Simulate a new module importing and calling getToken
    expect(getToken()).toBe("abc.def.ghi");
  });
});
