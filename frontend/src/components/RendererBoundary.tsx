import { Component, type ReactNode } from "react";

export class RendererBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <div
        className="center-notice"
        role="alert"
        style={{ pointerEvents: "auto" }}
      >
        <p>画布加载失败。节点数据与操作回执没有被替换为演示内容。</p>
        <button onClick={() => location.reload()}>重新加载页面</button>
      </div>
    ) : (
      this.props.children
    );
  }
}
