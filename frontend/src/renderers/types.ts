import type { Layout, RoutedEdge, Viewport } from "../geometry";
export interface CanvasProps {
  layout: Layout;
  edges: RoutedEdge[];
  viewport: Viewport;
  selected: number | null;
  focusedEdge: string | null;
  filter: string;
  tabID: number | null;
  onViewport: (viewport: Viewport) => void;
  onSelect: (id: number | null) => void;
  onHover: (id: string | null) => void;
  onNodeHover: (id: number | null) => void;
}
export const isMuted = (filter: string, role: string, availability: string) =>
  filter !== "all" &&
  (filter === "offline"
    ? availability === "online"
    : filter === "exception"
      ? availability === "online" && role !== "Candidate"
      : role !== filter);
