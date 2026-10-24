import "./node-badge.css";
import type { CSSProperties } from "react";
import { getNodeFontSizes, getNodePresentation } from "./nodePresentation";

export type NodeBadgeProps = {
  id: number;
  role: "Leader" | "Follower" | "Candidate" | "unknown";
  availability: "online" | "offline" | "unknown" | "identity-error";
  term?: number;
  selected?: boolean;
  diameter: number;
  zoom: number;
};

export function NodeBadge({
  id,
  role,
  availability,
  term,
  selected = false,
  diameter,
  zoom,
}: NodeBadgeProps) {
  const presentation = getNodePresentation(diameter, zoom);
  const fontSizes = getNodeFontSizes(zoom, diameter);
  const classes = [
    "node-badge",
    `node-badge--${role.toLowerCase()}`,
    `node-badge--${availability}`,
    `node-badge--${presentation}`,
    selected && "node-badge--selected",
  ]
    .filter(Boolean)
    .join(" ");
  const visibleRole = role === "unknown" ? "未知" : role;
  const availabilityLabel = {
    online: "在线",
    offline: "离线",
    unknown: "状态未知",
    "identity-error": "身份异常",
  }[availability];
  const description = [
    `节点 ${id}`,
    role === "unknown" ? "角色未知" : role,
    availabilityLabel,
    term === undefined ? undefined : `任期 ${term}`,
  ]
    .filter(Boolean)
    .join("，");

  return (
    <div
      className={classes}
      role="img"
      aria-label={description}
      title={description}
      style={{ "--node-id-size": `${fontSizes.id}px`, "--node-detail-size": `${fontSizes.detail}px` } as CSSProperties}
    >
      <span className="node-badge__id">{id}</span>
      {presentation === "detail" && (
        <span className="node-badge__meta">
          <span className="node-badge__role">{visibleRole}</span>
          {term !== undefined && (
            <span className="node-badge__term">T{term}</span>
          )}
        </span>
      )}
      {availability === "offline" && <span className="node-badge__status" aria-hidden="true">×</span>}
      {availability === "identity-error" && <span className="node-badge__status" aria-hidden="true">!</span>}
      {presentation === "dot" && <span className="node-badge__dot" aria-hidden="true" />}
    </div>
  );
}
