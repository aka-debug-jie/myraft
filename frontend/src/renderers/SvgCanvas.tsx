import { memo, useRef } from "react";
import { NodeBadge } from "../components/NodeBadge";
import { nearestEdge, zoomAt } from "../geometry";
import type { CanvasProps } from "./types";
import { isMuted } from "./types";

export const SvgCanvas = memo(function SvgCanvas(p: CanvasProps) {
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const dragged = useRef(false),
    down = useRef({ x: 0, y: 0 });
  const downNode = useRef<number | null>(null);
  const { layout, viewport: v } = p;
  return (
    <div
      className="svg-canvas"
      onPointerDown={(e) => {
        const node = (e.target as Element).closest<HTMLElement>("[data-node]");
        if (node && e.pointerType !== "touch") return;
        downNode.current = node ? Number(node.dataset.node) : null;
        e.currentTarget.setPointerCapture(e.pointerId);
        pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
        down.current = { x: e.clientX, y: e.clientY };
        dragged.current = pointers.current.size > 1;
      }}
      onPointerMove={(e) => {
        const old = pointers.current.get(e.pointerId),
          rect = e.currentTarget.getBoundingClientRect();
        if (old) {
          const now = { x: e.clientX, y: e.clientY };
          if (Math.hypot(now.x - down.current.x, now.y - down.current.y) > 4)
            dragged.current = true;
          if (pointers.current.size === 2) {
            const other = [...pointers.current.entries()].find(
              ([id]) => id !== e.pointerId,
            )![1];
            const before = Math.hypot(old.x - other.x, old.y - other.y),
              after = Math.hypot(now.x - other.x, now.y - other.y);
            if (before > 1)
              p.onViewport(
                zoomAt(
                  v,
                  {
                    x: (now.x + other.x) / 2 - rect.x,
                    y: (now.y + other.y) / 2 - rect.y,
                  },
                  after / before,
                ),
              );
          } else
            p.onViewport({
              ...v,
              x: v.x + now.x - old.x,
              y: v.y + now.y - old.y,
            });
          pointers.current.set(e.pointerId, now);
          return;
        }
        if ((e.target as Element).closest("button")) return;
        p.onHover(
          nearestEdge(
            p.edges,
            {
              x: (e.clientX - rect.x - v.x) / v.zoom,
              y: (e.clientY - rect.y - v.y) / v.zoom,
            },
            5 / v.zoom,
          ),
        );
      }}
      onPointerUp={(e) => {
        const owned = pointers.current.delete(e.pointerId);
        if (owned && !dragged.current) p.onSelect(downNode.current);
      }}
      onPointerCancel={(e) => pointers.current.delete(e.pointerId)}
      onPointerLeave={() => p.onHover(null)}
    >
      <svg
        className="edge-layer"
        width={layout.width}
        height={layout.height}
        aria-hidden="true"
      >
        <g transform={`translate(${v.x} ${v.y}) scale(${v.zoom})`}>
          {p.edges.map((edge) => (
            <path
              key={edge.id}
              data-relation={edge.id}
              d={edge.path}
              vectorEffect="non-scaling-stroke"
              className={`relation ${p.focusedEdge === edge.id ? "is-focused" : p.focusedEdge ? "is-dim" : ""}`}
            />
          ))}
        </g>
      </svg>
      <div
        className="node-layer"
        style={{ transform: `translate(${v.x}px,${v.y}px) scale(${v.zoom})` }}
      >
        {layout.nodes.map((n) => (
          <button
            key={n.id}
            data-node={n.id}
            data-role={n.role}
            data-availability={n.availability}
            className={`topology-node ${isMuted(p.filter, n.role, n.availability) ? "is-filtered" : ""}`}
            tabIndex={n.id === p.tabID ? 0 : -1}
            aria-label={`节点 ${n.id}，${n.role === "unknown" ? "未知" : n.role}`}
            aria-pressed={n.id === p.selected}
            style={{
              left: n.x - n.r,
              top: n.y - n.r,
              width: n.r * 2,
              height: n.r * 2,
            }}
            onClick={(e) => {
              e.stopPropagation();
              p.onSelect(n.id);
            }}
            onMouseEnter={() => p.onNodeHover(n.id)}
            onMouseLeave={() => p.onNodeHover(null)}
            onFocus={() => p.onNodeHover(n.id)}
            onBlur={() => p.onNodeHover(null)}
          >
            <NodeBadge
              id={n.id}
              role={n.role}
              availability={n.availability}
              term={n.status?.term}
              selected={n.id === p.selected}
              diameter={n.r * 2}
              zoom={v.zoom}
            />
          </button>
        ))}
      </div>
    </div>
  );
});
