import { expect, it } from "vitest";
import {
  getNodeFontSizes,
  getNodePresentation,
} from "../src/components/nodePresentation";

it("selects node detail from screen diameter", () => {
  expect(getNodePresentation(100, 0.72)).toBe("detail");
  expect(getNodePresentation(100, 0.719)).toBe("id");
  expect(getNodePresentation(40, 0.6)).toBe("id");
  expect(getNodePresentation(40, 0.599)).toBe("dot");
});

it("keeps text at least 12 screen pixels and makes the ID larger", () => {
  for (const zoom of [0.45, 1, 5]) {
    const sizes = getNodeFontSizes(zoom);
    expect(sizes.detail * zoom).toBeGreaterThanOrEqual(12);
    expect(sizes.id * zoom).toBeGreaterThanOrEqual(12);
    if (getNodePresentation(80, zoom) === "detail")
      expect(sizes.id).toBeGreaterThan(sizes.detail);
  }
});
