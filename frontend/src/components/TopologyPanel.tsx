import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "./Icon";
import { SvgCanvas } from "../renderers/SvgCanvas";
const FlowCanvas = lazy(() =>
  import("../renderers/FlowCanvas").then((module) => ({
    default: module.FlowCanvas,
  })),
);
import {
  HOME,
  focusNode,
  layoutNodes,
  nearestEdge,
  routeEdges,
  zoomAt,
  type Viewport,
} from "../geometry";
import type { Observation } from "../model";

interface Props {
  renderer: "svg" | "flow";
  observation: Observation;
  center: number | null;
  selected: number | null;
  filter: string;
  scope: string;
  onSelect: (id: number | null) => void;
  focusRequest: number;
}
export function TopologyPanel({
  renderer,
  observation,
  center,
  selected,
  filter,
  scope,
  onSelect,
  focusRequest,
}: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 800, height: 600 });
  const [viewport, setViewport] = useState<Viewport>(HOME);
  const [hover, setHover] = useState<string | null>(null),
    [nodeHover, setNodeHover] = useState<number | null>(null);
  const [minimap, setMinimap] = useState(false),
    [tabID, setTabID] = useState<number | null>(null);
  const [lastFocus, setLastFocus] = useState(focusRequest);
  const focusGeometry = useRef("");
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) =>
      setSize({
        width: entry.contentRect.width,
        height: entry.contentRect.height,
      }),
    );
    observer.observe(ref.current!);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    setViewport(HOME);
    setHover(null);
    setNodeHover(null);
    setTabID(null);
  }, [scope]);
  const membership = observation.nodes.map((n) => n.id).join(",");
  const geometry = useMemo(
    () => layoutNodes(observation.nodes, center, size.width, size.height),
    [membership, center, size],
  );
  const layout = useMemo(
    () => ({
      ...geometry,
      nodes: geometry.nodes.map((point, i) => ({
        ...point,
        ...observation.nodes[i],
      })),
    }),
    [geometry, observation.nodes],
  );
  const relationKey = observation.relations.map((e) => e.id).join(",");
  const edges = useMemo(
    () => routeEdges(geometry, observation.relations),
    [geometry, relationKey],
  );
  const current = useRef({ viewport, layout, edges });
  current.current = { viewport, layout, edges };
  useEffect(() => {
    const geometryKey = `${size.width}/${size.height}/${membership}/${center}`;
    if (
      lastFocus === focusRequest &&
      (focusRequest === 0 || focusGeometry.current === geometryKey)
    )
      return;
    setLastFocus(focusRequest);
    focusGeometry.current = geometryKey;
    if (selected !== null) setViewport(focusNode(layout, selected));
  }, [focusRequest, lastFocus, selected, layout, size, membership, center]);
  useEffect(() => {
    const host = ref.current!;
    const wheel = (event: WheelEvent) => {
      if ((event.target as Element).closest(".canvas-tools,.mini-map")) return;
      const { viewport: v } = current.current;
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault();
        event.stopPropagation();
        const rect = host.getBoundingClientRect();
        setViewport(
          zoomAt(
            v,
            { x: event.clientX - rect.x, y: event.clientY - rect.y },
            Math.exp(-event.deltaY * 0.002),
          ),
        );
      } else if (v.zoom !== 1 || v.x || v.y) {
        event.preventDefault();
        event.stopPropagation();
        setViewport({ ...v, x: v.x - event.deltaX, y: v.y - event.deltaY });
      }
    };
    host.addEventListener("wheel", wheel, { passive: false, capture: true });
    return () => host.removeEventListener("wheel", wheel, true);
  }, []);
  const focusedEdge =
    hover || edges.find((e) => e.from === (nodeHover ?? selected))?.id || null;
  const focused = edges.find((e) => e.id === focusedEdge);
  const selectedNode = observation.nodes.find((n) => n.id === selected);
  const filtered = observation.nodes.filter(
    (n) =>
      filter === "all" ||
      (filter === "offline"
        ? n.availability !== "online"
        : filter === "exception"
          ? n.availability !== "online" || n.role === "Candidate"
          : n.role === filter),
  );
  const activeID =
    tabID !== null && filtered.some((n) => n.id === tabID)
      ? tabID
      : selected !== null && filtered.some((n) => n.id === selected)
        ? selected
        : (filtered[0]?.id ?? null);
  const hasMoved =
    viewport.zoom !== 1 || Math.abs(viewport.x) > 1 || Math.abs(viewport.y) > 1;
  const props = {
    layout,
    edges,
    viewport,
    selected,
    filter,
    tabID: activeID,
    focusedEdge,
    onViewport: setViewport,
    onSelect,
    onHover: setHover,
    onNodeHover: setNodeHover,
  };
  return (
    <section
      className="topology-panel"
      data-renderer={renderer}
      aria-label={`${renderer === "svg" ? "SVG" : "React Flow"} 拓扑`}
    >
      <div className="canvas-caption">
        <span className="renderer-label">
          {renderer === "svg" ? "01 / SVG" : "02 / REACT FLOW"}
        </span>
        <span>
          {observation.nodes.length} 个成员 · {observation.relations.length}{" "}
          条有效报告关系
        </span>
      </div>
      <div
        className="canvas-host"
        ref={ref}
        data-members={observation.nodes.length}
        data-relations={observation.relations.length}
        data-drawn={edges.length}
        onKeyDown={(e) => {
          const target = (e.target as Element).closest<HTMLElement>(
            "[data-node]",
          );
          if (!target) return;
          const index = filtered.findIndex(
            (n) => n.id === Number(target.dataset.node),
          );
          let next = index;
          if (["ArrowRight", "ArrowDown"].includes(e.key))
            next = (index + 1) % filtered.length;
          else if (["ArrowLeft", "ArrowUp"].includes(e.key))
            next = (index - 1 + filtered.length) % filtered.length;
          else if (e.key === "Home") next = 0;
          else if (e.key === "End") next = filtered.length - 1;
          else if (e.key === "Escape") {
            onSelect(null);
            return;
          } else return;
          e.preventDefault();
          const id = filtered[next]?.id;
          if (id === undefined) return;
          setTabID(id);
          requestAnimationFrame(() =>
            ref.current
              ?.querySelector<HTMLElement>(`[data-node="${id}"]`)
              ?.focus({ preventScroll: true }),
          );
        }}
        onPointerMove={(e) => {
          if (
            renderer !== "flow" ||
            e.buttons ||
            (e.target as Element).closest("[data-node],button")
          )
            return;
          const rect = e.currentTarget.getBoundingClientRect();
          setHover(
            nearestEdge(
              edges,
              {
                x: (e.clientX - rect.x - viewport.x) / viewport.zoom,
                y: (e.clientY - rect.y - viewport.y) / viewport.zoom,
              },
              5 / viewport.zoom,
            ),
          );
        }}
        onPointerLeave={() => {
          setHover(null);
          setNodeHover(null);
        }}
      >
        {renderer === "svg" ? (
          <SvgCanvas {...props} />
        ) : (
          <Suspense
            fallback={
              <div className="center-notice" role="status">
                正在加载 React Flow 画布…
              </div>
            }
          >
            <FlowCanvas {...props} />
          </Suspense>
        )}
        {!center && (
          <div className="center-notice" role="status">
            <i />
            <strong>{observation.notice || "等待第二次 Leader 观测"}</strong>
          </div>
        )}
        {focused && (
          <div className="relation-caption" role="status">
            <span>节点 #{focused.from}</span>
            <Icon name="arrow" size={14} />
            <span>报告 Leader #{focused.to}</span>
            <small>T{focused.term} · 非复制确认</small>
          </div>
        )}
        {!focused && selectedNode?.role === "Leader" && (
          <div className="relation-caption">
            <span>Leader #{selectedNode.id}</span>
            <small>
              {
                observation.relations.filter((e) => e.to === selectedNode.id)
                  .length
              }{" "}
              个同任期 Follower 报告 · 非多数派证明
            </small>
          </div>
        )}
        <div className="canvas-tools" aria-label="画布工具">
          <button
            aria-label="放大"
            onClick={() =>
              setViewport(
                zoomAt(
                  viewport,
                  { x: size.width / 2, y: size.height / 2 },
                  1.25,
                ),
              )
            }
          >
            <Icon name="plus" />
          </button>
          <button
            aria-label="缩小"
            onClick={() =>
              setViewport(
                zoomAt(
                  viewport,
                  { x: size.width / 2, y: size.height / 2 },
                  0.8,
                ),
              )
            }
          >
            <Icon name="minus" />
          </button>
          <span className="zoom-label">{Math.round(viewport.zoom * 100)}%</span>
          <button
            aria-label="返回全景"
            title="返回全景"
            onClick={() => setViewport(HOME)}
          >
            <Icon name="fit" />
          </button>
          <button
            aria-label="聚焦选中节点"
            disabled={selected === null}
            onClick={() =>
              selected !== null && setViewport(focusNode(layout, selected))
            }
          >
            <Icon name="focus" />
          </button>
          <button
            aria-label="切换小地图"
            aria-pressed={minimap}
            onClick={() => setMinimap(!minimap)}
          >
            <Icon name="map" />
          </button>
        </div>
        {minimap && (
          <button
            className="mini-map"
            aria-label="小地图，点击返回全景"
            onClick={() => setViewport(HOME)}
          >
            <svg
              viewBox={`0 0 ${size.width} ${size.height}`}
              aria-hidden="true"
            >
              {layout.nodes.map((n) => (
                <circle
                  key={n.id}
                  cx={n.x}
                  cy={n.y}
                  r={n.id === center ? 12 : 6}
                  fill={
                    n.id === selected
                      ? "var(--text)"
                      : n.role === "Leader"
                        ? "var(--accent)"
                        : "var(--muted)"
                  }
                />
              ))}
              <rect
                x={-viewport.x / viewport.zoom}
                y={-viewport.y / viewport.zoom}
                width={size.width / viewport.zoom}
                height={size.height / viewport.zoom}
                fill="none"
                stroke="var(--accent)"
                strokeWidth="5"
              />
            </svg>
          </button>
        )}
        <div className="canvas-footnote">
          {hasMoved
            ? "局部视图 · 返回全景查看全部成员"
            : size.width < 600 && observation.nodes.length > 20
              ? "全体缩略 · 选择或搜索节点查看细节"
              : "固定成员 · 连线仅表示观测到的报告关系"}
        </div>
      </div>
    </section>
  );
}
