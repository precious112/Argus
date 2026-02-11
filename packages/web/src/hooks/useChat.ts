"use client";

import { useCallback, useRef, useState } from "react";
import type {
  AlertData,
  BudgetStatus,
  InvestigationData,
  ServerMessage,
} from "@/lib/protocol";
import type { Message } from "@/components/chat/MessageBubble";
import { generateId } from "@/lib/utils";

interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  result?: unknown;
  displayType?: string;
}

export interface SystemStatus {
  cpu_percent?: number;
  memory_percent?: number;
  memory_used_gb?: number;
  memory_total_gb?: number;
  disk_percent?: number;
  disk_free_gb?: number;
  load_avg?: string;
  cpu_count?: number;
}

export function useChat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isThinking, setIsThinking] = useState(false);
  const [activeToolCalls, setActiveToolCalls] = useState<ToolCall[]>([]);
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [alerts, setAlerts] = useState<AlertData[]>([]);
  const [budgetStatus, setBudgetStatus] = useState<BudgetStatus | null>(null);
  const streamingContentRef = useRef("");

  const dismissAlert = useCallback((alertId: string) => {
    setAlerts((prev) => prev.filter((a) => a.id !== alertId));
  }, []);

  const handleServerMessage = useCallback((msg: ServerMessage) => {
    switch (msg.type) {
      case "connected":
        break;

      case "system_status":
        setSystemStatus(msg.data as SystemStatus);
        break;

      case "thinking_start":
        setIsThinking(true);
        break;

      case "thinking_end":
        setIsThinking(false);
        break;

      case "assistant_message_start":
        streamingContentRef.current = "";
        break;

      case "assistant_message_delta": {
        const content = (msg.data.content as string) || "";
        streamingContentRef.current += content;
        const currentContent = streamingContentRef.current;

        setMessages((prev) => {
          const lastMsg = prev[prev.length - 1];
          if (lastMsg?.role === "assistant" && lastMsg.isStreaming) {
            return [
              ...prev.slice(0, -1),
              { ...lastMsg, content: currentContent },
            ];
          }
          return [
            ...prev,
            {
              id: generateId(),
              role: "assistant" as const,
              content: currentContent,
              timestamp: new Date(),
              isStreaming: true,
            },
          ];
        });
        break;
      }

      case "assistant_message_end":
        setMessages((prev) => {
          const lastMsg = prev[prev.length - 1];
          if (lastMsg?.role === "assistant" && lastMsg.isStreaming) {
            return [
              ...prev.slice(0, -1),
              { ...lastMsg, isStreaming: false, metadata: msg.data },
            ];
          }
          return prev;
        });
        streamingContentRef.current = "";
        break;

      case "tool_call": {
        const tc: ToolCall = {
          id: msg.data.id as string,
          name: msg.data.name as string,
          arguments: msg.data.arguments as Record<string, unknown>,
        };
        setActiveToolCalls((prev) => [...prev, tc]);

        setMessages((prev) => [
          ...prev,
          {
            id: `tc-${tc.id}`,
            role: "system" as const,
            content: `Calling tool: **${tc.name}**`,
            timestamp: new Date(),
            toolCall: tc,
          },
        ]);
        break;
      }

      case "tool_result": {
        const resultId = msg.data.id as string;
        setActiveToolCalls((prev) =>
          prev.map((tc) =>
            tc.id === resultId
              ? {
                  ...tc,
                  result: msg.data.result,
                  displayType: msg.data.display_type as string,
                }
              : tc,
          ),
        );

        setMessages((prev) =>
          prev.map((m) =>
            m.toolCall?.id === resultId
              ? {
                  ...m,
                  toolResult: {
                    displayType:
                      (msg.data.display_type as string) || "json_tree",
                    data: msg.data.result,
                  },
                }
              : m,
          ),
        );
        break;
      }

      case "action_request": {
        const actionReq = msg.data as unknown as import("@/lib/protocol").ActionRequest;
        setMessages((prev) => [
          ...prev,
          {
            id: `action-${actionReq.id}`,
            role: "system" as const,
            content: `Action proposed: ${actionReq.description}`,
            timestamp: new Date(),
            actionRequest: actionReq,
          },
        ]);
        break;
      }

      case "action_executing": {
        const execId = msg.data.id as string;
        setMessages((prev) => [
          ...prev,
          {
            id: `exec-${execId}`,
            role: "system" as const,
            content: `Executing action...`,
            timestamp: new Date(),
          },
        ]);
        break;
      }

      case "action_complete": {
        const completeData = msg.data;
        const exitCode = completeData.exit_code as number;
        const stdout = (completeData.stdout as string) || "";
        const summary = exitCode === 0
          ? `Action completed successfully${stdout ? `: ${stdout.slice(0, 200)}` : ""}`
          : `Action failed (exit code ${exitCode})`;
        setMessages((prev) => [
          ...prev,
          {
            id: generateId(),
            role: "system" as const,
            content: summary,
            timestamp: new Date(),
          },
        ]);
        break;
      }

      case "alert": {
        const alertData = msg.data as unknown as AlertData;
        setAlerts((prev) => [alertData, ...prev].slice(0, 20));
        break;
      }

      case "budget_update":
        setBudgetStatus(msg.data as unknown as BudgetStatus);
        break;

      case "investigation_start": {
        const inv = msg.data as unknown as InvestigationData;
        setMessages((prev) => [
          ...prev,
          {
            id: `inv-${inv.investigation_id}`,
            role: "system" as const,
            content: `Investigation started: ${inv.trigger || "Unknown trigger"} [${inv.severity || ""}]`,
            timestamp: new Date(),
          },
        ]);
        break;
      }

      case "investigation_update":
        // Updates stream into existing investigation message
        break;

      case "investigation_end": {
        const inv = msg.data as unknown as InvestigationData;
        setMessages((prev) => [
          ...prev,
          {
            id: generateId(),
            role: "assistant" as const,
            content:
              inv.summary || "Investigation completed with no summary.",
            timestamp: new Date(),
            metadata: {
              type: inv.type || "investigation",
              tokens_used: inv.tokens_used,
            },
          },
        ]);
        break;
      }

      case "error":
        setMessages((prev) => [
          ...prev,
          {
            id: generateId(),
            role: "system" as const,
            content: `Error: ${msg.data.message || "Unknown error"}`,
            timestamp: new Date(),
          },
        ]);
        setIsThinking(false);
        break;

      default:
        break;
    }
  }, []);

  const addUserMessage = useCallback((content: string) => {
    setMessages((prev) => [
      ...prev,
      {
        id: generateId(),
        role: "user" as const,
        content,
        timestamp: new Date(),
      },
    ]);
  }, []);

  return {
    messages,
    isThinking,
    activeToolCalls,
    systemStatus,
    alerts,
    budgetStatus,
    dismissAlert,
    handleServerMessage,
    addUserMessage,
  };
}
