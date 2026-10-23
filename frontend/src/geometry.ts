import type { Relation, ViewNode } from "./model";

export interface Point {
  x: number;
  y: number;
}
export interface PlacedNode extends ViewNode, Point {
  r: number;
}
export interface Layout {
  width: number;
  height: number;
  cx: number;
  cy: number;
  rx: number;
  ry: number;
  nodes: PlacedNode[];
  slots: Map<number, Point>;
}
export interface RoutedEdge extends Relation {
  path: string;
  points: Point[];
}
export interface Viewport {
  x: number;
  y: number;
  zoom: number;
}
export const HOME: Viewport = { x: 0, y: 0, zoom: 1 };

export function layoutNodes(
  nodes: ViewNode[],
  center: number | null,
  width: number,
  height: number,
): Layout {
  const cx = width / 2,
    cy = (height - 48) / 2,
    rx = Math.max(40, cx - 55),
    ry = Math.max(28, height / 2 - 96);
  const points: Point[] = [],
    lengths = [0];
  for (let i = 0; i <= 720; i++) {
    const angle = -Math.PI / 2 + (i * Math.PI) / 360;
    points.push({ x: cx + rx * Math.cos(angle), y: cy + ry * Math.sin(angle) });
    if (i)
      lengths.push(
        lengths[i - 1] +
          Math.hypot(
            points[i].x - points[i - 1].x,
            points[i].y - points[i - 1].y,
          ),
      );
  }
  const slots = new Map<number, Point>();
  let j = 1;
  nodes.forEach((node, i) => {
    const distance = (lengths.at(-1)! * i) / Math.max(1, nodes.length);
    while (j < 720 && lengths[j] < distance) j++;
    const fraction =
      (distance - lengths[j - 1]) / (lengths[j] - lengths[j - 1] || 1);
    slots.set(node.id, {
      x: points[j - 1].x + (points[j].x - points[j - 1].x) * fraction,
      y: points[j - 1].y + (points[j].y - points[j - 1].y) * fraction,
    });
  });
  let separation = Infinity;
  const positions = [...slots.values()];
  positions.forEach((point, i) => {
    const next = positions[(i + 1) % positions.length];
    if (i !== positions.length - 1 || positions.length > 1)
      separation = Math.min(
        separation,
        Math.hypot(point.x - next.x, point.y - next.y),
      );
  });
  const radius = Math.max(
    2,
    Math.min(width < 600 ? 25 : 40, (separation - 7) / 2, Math.min(rx, ry) / 3),
  );
  const centerRadius = Math.min(
    width < 600 ? 40 : 58,
    Math.max(10, Math.min(rx, ry) - radius - 10),
  );
  return {
    width,
    height,
    cx,
    cy,
    rx,
    ry,
    slots,
    nodes: nodes.map((node) => ({
      ...node,
      ...(node.id === center ? { x: cx, y: cy } : slots.get(node.id)!),
      r: node.id === center ? centerRadius : radius,
    })),
  };
}
export function segmentDistance(a: Point, b: Point, p: Point) {
  const dx = b.x - a.x,
    dy = b.y - a.y,
    length = dx * dx + dy * dy;
  const t = length
    ? Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / length))
    : 0;
  return Math.hypot(p.x - a.x - t * dx, p.y - a.y - t * dy);
}
function clip(a: PlacedNode, b: Point): Point {
  const length = Math.hypot(b.x - a.x, b.y - a.y) || 1;
  return {
    x: a.x + ((b.x - a.x) * a.r) / length,
    y: a.y + ((b.y - a.y) * a.r) / length,
  };
}
// The same routes feed both renderers. Exceptional off-center relations use
// a small visibility graph around obstacles; no fictitious relay is introduced.
export function routeEdges(
  layout: Layout,
  relations: Relation[],
): RoutedEdge[] {
  const byID = new Map(layout.nodes.map((n) => [n.id, n]));
  const clearance = Math.min(3, ...layout.nodes.map((n) => n.r / 2));
  return relations.flatMap((relation) => {
    const source = byID.get(relation.from),
      target = byID.get(relation.to);
    if (!source || !target) return [];
    const obstacles = layout.nodes.filter(
      (n) => n.id !== source.id && n.id !== target.id,
    );
    const clear = (a: Point, b: Point) =>
      obstacles.every((n) => segmentDistance(a, b, n) > n.r + clearance);
    let points: Point[] = [clip(source, target), clip(target, source)];
    if (!clear(points[0], points[1])) {
      const { cx, cy, rx, ry } = layout;
      const onRing = (n: PlacedNode) =>
        Math.abs(Math.hypot((n.x - cx) / rx, (n.y - cy) / ry) - 1) < 0.01;
      if (onRing(source) && onRing(target)) {
        const a = Math.atan2((source.y - cy) / ry, (source.x - cx) / rx),
          b = Math.atan2((target.y - cy) / ry, (target.x - cx) / rx);
        const margin = Math.max(...layout.nodes.map((n) => n.r)) + 10;
        const outer = (angle: number) => ({
          x: cx + (rx + margin) * Math.cos(angle),
          y: cy + (ry + margin) * Math.sin(angle),
        });
        const forward = (b - a + 2 * Math.PI) % (2 * Math.PI),
          deltas = [forward, forward - 2 * Math.PI].sort(
            (x, y) => Math.abs(x) - Math.abs(y),
          );
        for (const delta of deltas) {
          const steps = Math.ceil(Math.abs(delta) / 0.04),
            arc = Array.from({ length: steps + 1 }, (_, i) =>
              outer(a + (delta * i) / Math.max(1, steps)),
            );
          const detour = [
            clip(source, arc[0]),
            ...arc,
            clip(target, arc.at(-1)!),
          ];
          if (detour.slice(1).every((p, i) => clear(detour[i], p))) {
            points = detour;
            break;
          }
        }
      }
    }
    if (!points.slice(1).every((p, i) => clear(points[i], p))) {
      const candidates: Point[] = [source, target];
      // Only blockers of this chord need detour vertices. Every candidate segment
      // is still checked against all nodes, including obstacles off the chord.
      for (const n of obstacles.filter(
        (n) => segmentDistance(source, target, n) <= n.r + 5,
      ))
        for (let i = 0; i < 8; i++)
          candidates.push({
            x: n.x + (n.r + 8) * Math.cos((i * Math.PI) / 4),
            y: n.y + (n.r + 8) * Math.sin((i * Math.PI) / 4),
          });
      candidates.push(
        { x: 12, y: 12 },
        { x: layout.width - 12, y: 12 },
        { x: 12, y: layout.height - 12 },
        { x: layout.width - 12, y: layout.height - 12 },
      );
      const dist = candidates.map(() => Infinity),
        prev = candidates.map(() => -1),
        seen = new Set<number>();
      dist[0] = 0;
      for (let step = 0; step < candidates.length; step++) {
        let current = -1;
        for (let i = 0; i < candidates.length; i++)
          if (!seen.has(i) && (current < 0 || dist[i] < dist[current]))
            current = i;
        if (current < 0 || !Number.isFinite(dist[current]) || current === 1)
          break;
        seen.add(current);
        for (let i = 0; i < candidates.length; i++)
          if (!seen.has(i) && clear(candidates[current], candidates[i])) {
            const value =
              dist[current] +
              Math.hypot(
                candidates[current].x - candidates[i].x,
                candidates[current].y - candidates[i].y,
              );
            if (value < dist[i]) {
              dist[i] = value;
              prev[i] = current;
            }
          }
      }
      if (!Number.isFinite(dist[1])) return [];
      points = [];
      for (let i = 1; i >= 0; i = prev[i]) points.unshift(candidates[i]);
      points[0] = clip(source, points[1]);
      points[points.length - 1] = clip(target, points.at(-2)!);
    }
    return [
      {
        ...relation,
        points,
        path: points
          .map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(3)},${p.y.toFixed(3)}`)
          .join(" "),
      },
    ];
  });
}
export function nearestEdge(
  edges: RoutedEdge[],
  point: Point,
  threshold: number,
): string | null {
  let best = threshold,
    found: string | null = null;
  for (const edge of edges)
    for (let i = 1; i < edge.points.length; i++) {
      const distance = segmentDistance(
        edge.points[i - 1],
        edge.points[i],
        point,
      );
      if (distance < best) {
        best = distance;
        found = edge.id;
      }
    }
  return found;
}
export function zoomAt(view: Viewport, point: Point, factor: number): Viewport {
  const zoom = Math.max(0.45, Math.min(5, view.zoom * factor));
  return {
    zoom,
    x: point.x - ((point.x - view.x) * zoom) / view.zoom,
    y: point.y - ((point.y - view.y) * zoom) / view.zoom,
  };
}
export function focusNode(layout: Layout, id: number): Viewport {
  const node = layout.nodes.find((n) => n.id === id);
  if (!node) return HOME;
  const leader = layout.nodes.find(
    (n) =>
      n.id === node.status?.leader_id &&
      n.role === "Leader" &&
      n.status?.term === node.status?.term,
  );
  if (node.role === "Follower" && leader) {
    const left = Math.min(node.x - node.r, leader.x - leader.r),
      right = Math.max(node.x + node.r, leader.x + leader.r);
    const top = Math.min(node.y - node.r, leader.y - leader.r),
      bottom = Math.max(node.y + node.r, leader.y + leader.r);
    const zoom = Math.max(
      0.45,
      Math.min(
        4,
        (layout.width - 100) / (right - left),
        (layout.height - 150) / (bottom - top),
      ),
    );
    return {
      zoom,
      x: layout.width / 2 - ((left + right) * zoom) / 2,
      y: (layout.height - 40) / 2 - ((top + bottom) * zoom) / 2,
    };
  }
  const zoom = Math.min(4, Math.max(1.5, 30 / node.r));
  return {
    zoom,
    x: layout.width / 2 - node.x * zoom,
    y: layout.height / 2 - node.y * zoom,
  };
}
