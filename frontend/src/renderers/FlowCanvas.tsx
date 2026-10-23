import { memo, useMemo } from "react";
import {
  ReactFlow,
  Handle,
  Position,
  type Node,
  type Edge,
  type NodeProps,
  type EdgeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { NodeBadge } from "../components/NodeBadge";
import type { PlacedNode } from "../geometry";
import type { CanvasProps } from "./types";
import { isMuted } from "./types";

type RaftNode = Node<
  {
    node: PlacedNode;
    chosen: boolean;
    tab: boolean;
    label: boolean;
    filtered: boolean;
  },
  "raft"
>;
const FlowNode = memo(function FlowNode({ data }: NodeProps<RaftNode>) {
  const n = data.node;
  return (
    <>
      <Handle
        type="source"
        position={Position.Top}
        className="invisible-handle"
      />
      <button
        className={`topology-node flow-node-button ${data.filtered ? "is-filtered" : ""}`}
        data-node={n.id}
        data-role={n.role}
        data-availability={n.availability}
        aria-label={`节点 ${n.id}，${n.role === "unknown" ? "未知" : n.role}`}
        aria-pressed={data.chosen}
        tabIndex={data.tab ? 0 : -1}
      >
        <NodeBadge
          id={n.id}
          role={n.role}
          availability={n.availability}
          term={n.status?.term}
          selected={data.chosen}
          compact={n.r < 32}
          label={data.label}
        />
      </button>
      <Handle
        type="target"
        position={Position.Bottom}
        className="invisible-handle"
      />
    </>
  );
});
type RaftEdge = Edge<{ path: string; focus: boolean; dim: boolean }, "raft">;
function FlowEdge({ id, data }: EdgeProps<RaftEdge>) {
  return (
    <path
      data-relation={id}
      className={`relation ${data!.focus ? "is-focused" : data!.dim ? "is-dim" : ""}`}
      d={data!.path}
      vectorEffect="non-scaling-stroke"
    />
  );
}
const nodeTypes = { raft: FlowNode },
  edgeTypes = { raft: FlowEdge };
export const FlowCanvas = memo(function FlowCanvas(p: CanvasProps) {
  const nodes = useMemo<RaftNode[]>(
    () =>
      p.layout.nodes.map((n) => ({
        id: String(n.id),
        type: "raft",
        position: { x: n.x - n.r, y: n.y - n.r },
        width: n.r * 2,
        height: n.r * 2,
        style: { width: n.r * 2, height: n.r * 2 },
        data: {
          node: n,
          chosen: n.id === p.selected,
          tab: n.id === p.tabID,
          label: n.r * 2 * p.viewport.zoom >= 22,
          filtered: isMuted(p.filter, n.role, n.availability),
        },
      })),
    [p.layout, p.selected, p.tabID, p.viewport.zoom, p.filter],
  );
  const edges = useMemo<RaftEdge[]>(
    () =>
      p.edges.map((e) => ({
        id: e.id,
        source: String(e.from),
        target: String(e.to),
        type: "raft",
        data: {
          path: e.path,
          focus: e.id === p.focusedEdge,
          dim: !!p.focusedEdge && e.id !== p.focusedEdge,
        },
      })),
    [p.edges, p.focusedEdge],
  );
  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      viewport={p.viewport}
      onViewportChange={p.onViewport}
      minZoom={0.45}
      maxZoom={5}
      nodesDraggable={false}
      nodesConnectable={false}
      nodesFocusable={false}
      edgesFocusable={false}
      elementsSelectable={false}
      deleteKeyCode={null}
      selectionKeyCode={null}
      panActivationKeyCode={null}
      zoomOnScroll={false}
      zoomOnDoubleClick={false}
      zoomOnPinch={true}
      panOnScroll={false}
      onNodeClick={(_, node) => p.onSelect(Number(node.id))}
      onPaneClick={() => p.onSelect(null)}
      onNodeMouseEnter={(_, node) => p.onNodeHover(Number(node.id))}
      onNodeMouseLeave={() => p.onNodeHover(null)}
      proOptions={{ hideAttribution: false }}
    />
  );
});
