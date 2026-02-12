import type { ActionRequest } from "@/lib/protocol";
import { ToolResultCard } from "./ToolResultCard";
import { MarkdownContent } from "./MarkdownContent";

export type ResponseSegment =
  | { type: "text"; content: string }
  | {
      type: "tool";
      toolCall: { id: string; name: string; arguments: Record<string, unknown> };
      toolResult?: { displayType: string; data: unknown };
    };

export interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: Date;
  isStreaming?: boolean;
  metadata?: Record<string, unknown>;
  segments?: ResponseSegment[];
  toolCall?: {
    id: string;
    name: string;
    arguments: Record<string, unknown>;
  };
  toolResult?: {
    displayType: string;
    data: unknown;
  };
  actionRequest?: ActionRequest;
}

interface MessageBubbleProps {
  message: Message;
  onApproveAction?: (actionId: string) => void;
  onRejectAction?: (actionId: string) => void;
}

export function MessageBubble({ message, onApproveAction, onRejectAction }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const isSystem = message.role === "system";

  // Action approval messages
  if (isSystem && message.actionRequest) {
    const { ActionApproval } = require("./ActionApproval");
    return (
      <div className="flex justify-start">
        <div className="max-w-[90%]">
          <ActionApproval
            action={message.actionRequest}
            onApprove={onApproveAction || (() => {})}
            onReject={onRejectAction || (() => {})}
          />
        </div>
      </div>
    );
  }

  // Tool call messages get special rendering (legacy separate bubbles)
  if (isSystem && message.toolCall) {
    return (
      <div className="flex justify-start">
        <div className="max-w-[90%] rounded-lg border border-[var(--border)] bg-[var(--card)] px-4 py-3 text-sm">
          <div className="mb-1 flex items-center gap-2 text-xs text-[var(--muted)]">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-argus-400" />
            <span>Tool: {message.toolCall.name}</span>
          </div>

          {message.toolResult ? (
            <ToolResultCard
              displayType={message.toolResult.displayType}
              data={message.toolResult.data}
            />
          ) : (
            <div className="text-[var(--muted)]">Executing...</div>
          )}
        </div>
      </div>
    );
  }

  // System error messages
  if (isSystem) {
    return (
      <div className="flex justify-center">
        <div className="rounded-lg bg-red-900/20 px-4 py-2 text-sm text-red-400">
          {message.content}
        </div>
      </div>
    );
  }

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[80%] rounded-lg px-4 py-3 text-sm leading-relaxed ${
          isUser
            ? "bg-argus-600 text-white"
            : "bg-[var(--card)] text-[var(--foreground)]"
        }`}
      >
        {!isUser && (
          <div className="mb-1 flex items-center gap-2 text-xs font-medium text-argus-400">
            <span>Argus</span>
            {message.isStreaming && (
              <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-argus-400" />
            )}
          </div>
        )}
        {!isUser && message.segments && message.segments.length > 0 ? (
          <div className="space-y-3">
            {message.segments.map((seg, i) =>
              seg.type === "text" ? (
                <MarkdownContent key={i} content={seg.content} />
              ) : (
                <div
                  key={i}
                  className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2"
                >
                  <div className="mb-1 flex items-center gap-2 text-xs text-[var(--muted)]">
                    <span className="inline-block h-1.5 w-1.5 rounded-full bg-argus-400" />
                    <span>Tool: {seg.toolCall.name}</span>
                  </div>
                  {seg.toolResult ? (
                    <ToolResultCard
                      displayType={seg.toolResult.displayType}
                      data={seg.toolResult.data}
                    />
                  ) : (
                    <div className="text-[var(--muted)]">Executing...</div>
                  )}
                </div>
              ),
            )}
          </div>
        ) : !isUser ? (
          <MarkdownContent content={message.content} />
        ) : (
          <div className="whitespace-pre-wrap">{message.content}</div>
        )}
        <div
          className={`mt-1 text-xs ${isUser ? "text-argus-200" : "text-[var(--muted)]"}`}
        >
          {message.timestamp.toLocaleTimeString()}
        </div>
      </div>
    </div>
  );
}
