export interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: Date;
  toolCalls?: Array<{
    name: string;
    args: Record<string, unknown>;
  }>;
  toolResult?: {
    displayType: string;
    data: unknown;
  };
}

interface MessageBubbleProps {
  message: Message;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";

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
          <div className="mb-1 text-xs font-medium text-argus-400">Argus</div>
        )}
        <div className="whitespace-pre-wrap">{message.content}</div>
        <div
          className={`mt-1 text-xs ${isUser ? "text-argus-200" : "text-[var(--muted)]"}`}
        >
          {message.timestamp.toLocaleTimeString()}
        </div>
      </div>
    </div>
  );
}
