"use client";

import { useState, useRef, useEffect } from "react";
import { MessageBubble, type Message } from "./MessageBubble";

export function ChatContainer() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "welcome",
      role: "assistant",
      content:
        "Hello! I'm Argus, your AI observability agent. I can help you monitor your systems, search logs, analyze metrics, and investigate issues. What would you like to know?",
      timestamp: new Date(),
    },
  ]);
  const [input, setInput] = useState("");
  const [isConnected, setIsConnected] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;

    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: input,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");

    // TODO: Send via WebSocket in Phase 1
    const placeholderResponse: Message = {
      id: crypto.randomUUID(),
      role: "assistant",
      content:
        "Agent not yet connected. WebSocket integration coming in Phase 1.",
      timestamp: new Date(),
    };
    setTimeout(() => {
      setMessages((prev) => [...prev, placeholderResponse]);
    }, 500);
  };

  return (
    <div className="flex h-full flex-col">
      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-4 py-6">
        <div className="mx-auto max-w-3xl space-y-4">
          {messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input area */}
      <div className="border-t border-[var(--border)] px-4 py-4">
        <form
          onSubmit={handleSubmit}
          className="mx-auto flex max-w-3xl items-center gap-3"
        >
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask Argus about your system..."
            className="flex-1 rounded-lg border border-[var(--border)] bg-[var(--card)] px-4 py-2.5 text-sm text-[var(--foreground)] placeholder-[var(--muted)] outline-none focus:border-argus-500"
          />
          <button
            type="submit"
            disabled={!input.trim()}
            className="rounded-lg bg-argus-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-argus-500 disabled:opacity-40 disabled:hover:bg-argus-600"
          >
            Send
          </button>
        </form>
      </div>
    </div>
  );
}
