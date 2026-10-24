export type NodePresentation = "dot" | "id" | "detail";

export function getNodePresentation(
  diameter: number,
  zoom: number,
): NodePresentation {
  const screenDiameter = diameter * zoom;
  if (screenDiameter >= 72) return "detail";
  if (screenDiameter >= 24) return "id";
  return "dot";
}

export function getNodeFontSizes(zoom: number, diameter = 80) {
  return {
    id: Math.min(34, Math.max(12, diameter * zoom * 0.28)) / zoom,
    detail: 12 / zoom,
  };
}
