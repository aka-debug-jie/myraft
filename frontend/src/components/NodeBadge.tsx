import "./node-badge.css";

export type NodeBadgeProps = {
  id: number;
  role: "Leader" | "Follower" | "Candidate" | "unknown";
  availability: "online" | "offline" | "unknown" | "identity-error";
  term?: number;
  selected?: boolean;
  compact?: boolean;
  label?: boolean;
};

export function NodeBadge({
  id,
  role,
  availability,
  term,
  selected = false,
  compact = false,
  label = true,
}: NodeBadgeProps) {
  const classes = [
    "node-badge",
    `node-badge--${role.toLowerCase()}`,
    `node-badge--${availability}`,
    compact && "node-badge--compact",
    selected && "node-badge--selected",
    !label && "node-badge--icon-only",
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
    >
      <span className="node-badge__id">{id}</span>
      {label && (
        <span className="node-badge__meta">
          <span className="node-badge__role">{visibleRole}</span>
          {term !== undefined && (
            <span className="node-badge__term">T{term}</span>
          )}
        </span>
      )}
    </div>
  );
}
