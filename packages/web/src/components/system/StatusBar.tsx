"use client";

export function StatusBar() {
  // TODO: Phase 2 - Live system status from WebSocket
  return (
    <div className="flex items-center gap-4 border-b border-[var(--border)] bg-[var(--card)] px-4 py-1.5 text-xs text-[var(--muted)]">
      <div className="flex items-center gap-1.5">
        <span className="h-2 w-2 rounded-full bg-yellow-500" />
        <span>Agent: Initializing</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span>CPU: --</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span>Memory: --</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span>Disk: --</span>
      </div>
    </div>
  );
}
