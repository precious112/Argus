"use client";

import { useRef, useEffect, useState } from "react";
import { MessageBubble } from "./MessageBubble";
import { AlertBanner } from "@/components/system/AlertBanner";
import { StatusBar } from "@/components/system/StatusBar";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useChat } from "@/hooks/useChat";
import { useActions } from "@/hooks/useActions";

const WS_URL =
  process.env.NEXT_PUBLIC_AGENT_WS_URL || "ws://localhost:7600/api/v1/ws";

export function ChatContainer() {
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const {
    messages,
    isThinking,
    systemStatus,
    alerts,
    budgetStatus,
    dismissAlert,
    handleServerMessage,
    addUserMessage,
  } = useChat();

  const { isConnected, send, sendUserMessage } = useWebSocket({
    url: WS_URL,
    onMessage: handleServerMessage,
  });

  const { approveAction, rejectAction } = useActions(send);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;

    addUserMessage(input);
    sendUserMessage(input);
    setInput("");
  };

  return (
    <div className="flex h-full flex-col">
      {/* Status bar with live metrics */}
      <StatusBar
        status={systemStatus}
        isConnected={isConnected}
        budgetStatus={budgetStatus}
      />

      {/* Alert banner */}
      <AlertBanner alerts={alerts} onDismiss={dismissAlert} />

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-4 py-6">
        <div className="mx-auto max-w-3xl space-y-4">
          {messages.length === 0 && (
            <div className="py-20 text-center">
              <h2 className="mb-2 text-lg font-medium text-[var(--foreground)]">
                Welcome to Argus
              </h2>
              <p className="text-sm text-[var(--muted)]">
                Ask me about your system — logs, metrics, processes, errors.
              </p>
            </div>
          )}

          {messages.map((msg) => (
            <MessageBubble
              key={msg.id}
              message={msg}
              onApproveAction={approveAction}
              onRejectAction={rejectAction}
            />
          ))}

          {isThinking && (
            <div className="flex justify-start">
              <div className="rounded-lg bg-[var(--card)] px-4 py-3 text-sm text-[var(--muted)]">
                <span className="inline-flex items-center gap-1">
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-argus-400 [animation-delay:-0.3s]" />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-argus-400 [animation-delay:-0.15s]" />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-argus-400" />
                </span>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input area */}
      <div className="border-t border-[var(--border)] px-4 py-4">
        <form
          onSubmit={handleSubmit}
          className="mx-auto flex max-w-3xl items-center gap-3"
        >
          <div className="relative flex-1">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={
                isConnected
                  ? "Ask Argus about your system..."
                  : "Connecting to agent..."
              }
              disabled={!isConnected}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--card)] px-4 py-2.5 text-sm text-[var(--foreground)] placeholder-[var(--muted)] outline-none focus:border-argus-500 disabled:opacity-50"
            />
          </div>
          <button
            type="submit"
            disabled={!input.trim() || !isConnected}
            className="rounded-lg bg-argus-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-argus-500 disabled:opacity-40 disabled:hover:bg-argus-600"
          >
            Send
          </button>
        </form>
        <div className="mx-auto mt-1.5 flex max-w-3xl items-center gap-2 text-xs text-[var(--muted)]">
          <span
            className={`inline-block h-1.5 w-1.5 rounded-full ${isConnected ? "bg-green-500" : "bg-red-500"}`}
          />
          <span>{isConnected ? "Connected" : "Disconnected"}</span>
        </div>
      </div>
    </div>
  );
}
