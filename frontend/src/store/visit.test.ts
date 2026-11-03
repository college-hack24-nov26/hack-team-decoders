/**
 * Visit-progress store tests.
 *
 * The behaviour that matters: the completed interview id survives navigation
 * between the interview, document and done screens, and is cleared when the
 * kiosk is handed to the next patient. Wave 4 reads this id to call
 * POST /summaries/generate, so losing it silently would break the summariser.
 */

import { beforeEach, describe, expect, it } from "vitest";
import { clearVisit, getCompletedInterview, setCompletedInterview } from "./visit";

describe("visit progress", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("reports no completed interview on a fresh visit", () => {
    expect(getCompletedInterview()).toBeNull();
  });

  it("remembers the completed interview session across screens", () => {
    setCompletedInterview("11111111-2222-3333-4444-555555555555");
    expect(getCompletedInterview()).toBe("11111111-2222-3333-4444-555555555555");
  });

  it("clears the trail so the next patient does not inherit it", () => {
    setCompletedInterview("11111111-2222-3333-4444-555555555555");
    clearVisit();
    expect(getCompletedInterview()).toBeNull();
  });
});
