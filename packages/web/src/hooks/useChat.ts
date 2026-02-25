"use client";

import { useCallback, useRef, useState } from "react";
import type {
  ActionRequest,
  AlertData,
  BudgetStatus,
  InvestigationData,
  ServerMessage,
} from "@/lib/protocol";
import type { Message, ResponseSegment } from "@/components/chat/MessageBubble";
import { apiFetch } from "@/lib/api";
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
  const [agentMode, setAgentMode] = useState<string>("full");
  const [alerts, setAlerts] = useState<AlertData[]>([]);
  const [budgetStatus, setBudgetStatus] = useState<BudgetStatus | null>(null);
  const streamingContentRef = useRef("");

  // Refs for tracking grouped response segments
  const currentResponseIdRef = useRef<string | null>(null);
  const segmentsRef = useRef<ResponseSegment[]>([]);
  const currentTextRef = useRef("");
  const lastEventTypeRef = useRef<string>("");

  const dismissAlert = useCallback((alertId: string) => {
    setAlerts((prev) => prev.filter((a) => a.id !== alertId));
  }, []);

  const acknowledgeAlert = useCallback(async (alertId: string) => {
    const apiBase =
      process.env.NEXT_PUBLIC_ARGUS_URL || "http://localhost:7600";
    try {
      await apiFetch(`${apiBase}/api/v1/alerts/${alertId}/acknowledge`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      // Update local state
      setAlerts((prev) =>
        prev.map((a) =>
          a.id === alertId ? { ...a, status: "acknowledged" } : a,
        ),
      );
    } catch {
      // ignore
    }
  }, []);

  /** Flush any accumulated text into a text segment. */
  const finalizeTextSegment = useCallback(() => {
    if (currentTextRef.current.trim()) {
      // Check if the last segment is already a text segment we can update
      const lastSeg = segmentsRef.current[segmentsRef.current.length - 1];
      if (lastSeg && lastSeg.type === "text" && lastEventTypeRef.current !== "tool_result") {
        lastSeg.content = currentTextRef.current;
      }
      // Text was already added as a segment during delta — nothing more to do
    }
    currentTextRef.current = "";
  }, []);

  /** Update the current grouped message in state with latest segments. */
  const updateGroupedMessage = useCallback(
    (overrides?: Partial<Message>) => {
      const id = currentResponseIdRef.current;
      if (!id) return;

      const segs = [...segmentsRef.current];
      // Build full content from text segments for backward compat
      const fullContent = segs
        .filter((s): s is ResponseSegment & { type: "text" } => s.type === "text")
        .map((s) => s.content)
        .join("\n\n");

      setMessages((prev) =>
        prev.map((m) =>
          m.id === id
            ? { ...m, content: fullContent, segments: segs, ...overrides }
            : m,
        ),
      );
    },
    [],
  );

  const handleServerMessage = useCallback(
    (msg: ServerMessage) => {
      switch (msg.type) {
        case "connected":
          break;

        case "system_status":
          if (msg.data.mode) {
            setAgentMode(msg.data.mode as string);
          }
          setSystemStatus(msg.data as SystemStatus);
          break;

        case "thinking_start":
          setIsThinking(true);
          break;

        case "thinking_end":
          setIsThinking(false);
          break;

        case "assistant_message_start": {
          // Start a new grouped assistant message
          const id = generateId();
          currentResponseIdRef.current = id;
          segmentsRef.current = [];
          currentTextRef.current = "";
          lastEventTypeRef.current = "";
          streamingContentRef.current = "";

          setMessages((prev) => [
            ...prev,
            {
              id,
              role: "assistant" as const,
              content: "",
              timestamp: new Date(),
              isStreaming: true,
              segments: [],
            },
          ]);
          break;
        }

        case "assistant_message_delta": {
          const content = (msg.data.content as string) || "";

          // If we just received a tool_result, start a new text segment
          if (lastEventTypeRef.current === "tool_result") {
            currentTextRef.current = "";
            segmentsRef.current.push({ type: "text", content: "" });
          }
          // If no text segment exists yet, create one
          else if (
            segmentsRef.current.length === 0 ||
            segmentsRef.current[segmentsRef.current.length - 1].type !== "text"
          ) {
            segmentsRef.current.push({ type: "text", content: "" });
          }

          currentTextRef.current += content;
          streamingContentRef.current += content;

          // Update the current text segment in place
          const lastSeg = segmentsRef.current[segmentsRef.current.length - 1];
          if (lastSeg && lastSeg.type === "text") {
            lastSeg.content = currentTextRef.current;
          }

          lastEventTypeRef.current = "assistant_message_delta";

          updateGroupedMessage();
          break;
        }

        case "assistant_message_end": {
          finalizeTextSegment();
          updateGroupedMessage({ isStreaming: false, metadata: msg.data });
          // Clear refs
          currentResponseIdRef.current = null;
          segmentsRef.current = [];
          currentTextRef.current = "";
          lastEventTypeRef.current = "";
          streamingContentRef.current = "";
          break;
        }

        case "tool_call": {
          const tc: ToolCall = {
            id: msg.data.id as string,
            name: msg.data.name as string,
            arguments: msg.data.arguments as Record<string, unknown>,
          };
          setActiveToolCalls((prev) => [...prev, tc]);

          // If we have a grouped message, add as segment
          if (currentResponseIdRef.current) {
            // Finalize any pending text
            finalizeTextSegment();

            segmentsRef.current.push({
              type: "tool",
              toolCall: { id: tc.id, name: tc.name, arguments: tc.arguments },
            });

            lastEventTypeRef.current = "tool_call";
            updateGroupedMessage();
          } else {
            // Fallback: create separate system message (legacy behavior)
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
          }
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

          // If we have a grouped message, update the matching tool segment
          if (currentResponseIdRef.current) {
            const idx = segmentsRef.current.findIndex(
              (s) => s.type === "tool" && s.toolCall.id === resultId,
            );
            if (idx !== -1) {
              const seg = segmentsRef.current[idx];
              if (seg.type === "tool") {
                segmentsRef.current[idx] = {
                  ...seg,
                  toolResult: {
                    displayType:
                      (msg.data.display_type as string) || "json_tree",
                    data: msg.data.result,
                  },
                };
              }
            }

            lastEventTypeRef.current = "tool_result";
            updateGroupedMessage();
          } else {
            // Message already finalized — find matching tool segment in recent messages
            setMessages((prev) => {
              for (let i = prev.length - 1; i >= 0; i--) {
                const m = prev[i];
                if (m.role === "assistant" && m.segments) {
                  const segIdx = m.segments.findIndex(
                    (s) => s.type === "tool" && s.toolCall.id === resultId,
                  );
                  if (segIdx !== -1) {
                    const newSegs = [...m.segments];
                    const seg = newSegs[segIdx];
                    if (seg.type === "tool") {
                      newSegs[segIdx] = {
                        ...seg,
                        toolResult: {
                          displayType:
                            (msg.data.display_type as string) || "json_tree",
                          data: msg.data.result,
                        },
                      };
                    }
                    const updated = [...prev];
                    updated[i] = { ...m, segments: newSegs };
                    return updated;
                  }
                }
              }
              // Legacy: separate system message with toolCall
              return prev.map((m) =>
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
              );
            });
          }
          break;
        }

        case "action_request": {
          const actionReq = msg.data as unknown as ActionRequest;

          if (currentResponseIdRef.current) {
            // Active streaming message — push segment inline
            finalizeTextSegment();
            segmentsRef.current.push({
              type: "action_request",
              actionRequest: actionReq,
            });
            lastEventTypeRef.current = "action_request";
            updateGroupedMessage();
          } else {
            // Message already finalized — append to most recent assistant message
            setMessages((prev) => {
              for (let i = prev.length - 1; i >= 0; i--) {
                if (prev[i].role === "assistant" && prev[i].segments) {
                  const updated = [...prev];
                  updated[i] = {
                    ...prev[i],
                    segments: [
                      ...(prev[i].segments || []),
                      {
                        type: "action_request" as const,
                        actionRequest: actionReq,
                      },
                    ],
                  };
                  return updated;
                }
              }
              // No assistant message — fall back to system message
              return [
                ...prev,
                {
                  id: `action-${actionReq.id}`,
                  role: "system" as const,
                  content: `Action proposed: ${actionReq.description}`,
                  timestamp: new Date(),
                  actionRequest: actionReq,
                },
              ];
            });
          }
          break;
        }

        case "action_executing": {
          const execId = msg.data.id as string;
          if (currentResponseIdRef.current) {
            finalizeTextSegment();
            segmentsRef.current.push({
              type: "action",
              actionId: execId,
              status: "executing",
              content: "Executing action...",
            });
            lastEventTypeRef.current = "action_executing";
            updateGroupedMessage();
          } else {
            // Append to most recent assistant message
            setMessages((prev) => {
              for (let i = prev.length - 1; i >= 0; i--) {
                if (prev[i].role === "assistant" && prev[i].segments) {
                  const updated = [...prev];
                  updated[i] = {
                    ...prev[i],
                    segments: [
                      ...(prev[i].segments || []),
                      {
                        type: "action" as const,
                        actionId: execId,
                        status: "executing" as const,
                        content: "Executing action...",
                      },
                    ],
                  };
                  return updated;
                }
              }
              // No assistant message — fall back to system message
              return [
                ...prev,
                {
                  id: `exec-${execId}`,
                  role: "system" as const,
                  content: "Executing action...",
                  timestamp: new Date(),
                  metadata: { status: "executing" },
                },
              ];
            });
          }
          break;
        }

        case "action_complete": {
          const completeData = msg.data;
          const exitCode = completeData.exit_code as number;
          const stdout = (completeData.stdout as string) || "";
          const actionId = (completeData.id as string) || "";
          const isSuccess = exitCode === 0;
          const summary = isSuccess
            ? `Action completed successfully${stdout ? `: ${stdout.slice(0, 200)}` : ""}`
            : `Action failed (exit code ${exitCode})`;
          const status = isSuccess ? "success" : "error";

          if (currentResponseIdRef.current) {
            // Mark matching action_request segment as resolved
            for (const seg of segmentsRef.current) {
              if (
                seg.type === "action_request" &&
                seg.actionRequest.id === actionId
              ) {
                seg.resolved = true;
              }
            }

            // Update existing executing segment or add new one
            const existingIdx = segmentsRef.current.findIndex(
              (s) =>
                s.type === "action" &&
                s.actionId === actionId &&
                s.status === "executing",
            );
            if (existingIdx !== -1) {
              segmentsRef.current[existingIdx] = {
                type: "action",
                actionId,
                status,
                content: summary,
              };
            } else {
              finalizeTextSegment();
              segmentsRef.current.push({
                type: "action",
                actionId: actionId || generateId(),
                status,
                content: summary,
              });
            }
            lastEventTypeRef.current = "action_complete";
            updateGroupedMessage();
          } else {
            // Update executing segment in most recent assistant message, or append
            setMessages((prev) => {
              for (let i = prev.length - 1; i >= 0; i--) {
                const m = prev[i];
                if (m.role === "assistant" && m.segments) {
                  const newSegs = [...m.segments];

                  // Mark matching action_request segment as resolved
                  for (let j = 0; j < newSegs.length; j++) {
                    const s = newSegs[j];
                    if (
                      s.type === "action_request" &&
                      s.actionRequest.id === actionId
                    ) {
                      newSegs[j] = { ...s, resolved: true };
                    }
                  }

                  const execIdx = newSegs.findIndex(
                    (s) =>
                      s.type === "action" &&
                      s.actionId === actionId &&
                      s.status === "executing",
                  );
                  if (execIdx !== -1) {
                    newSegs[execIdx] = {
                      type: "action",
                      actionId,
                      status,
                      content: summary,
                    };
                  } else {
                    newSegs.push({
                      type: "action",
                      actionId: actionId || generateId(),
                      status,
                      content: summary,
                    });
                  }
                  const updated = [...prev];
                  updated[i] = { ...m, segments: newSegs };
                  return updated;
                }
              }
              // No assistant message — fall back to system message
              return [
                ...prev,
                {
                  id: generateId(),
                  role: "system" as const,
                  content: summary,
                  timestamp: new Date(),
                  metadata: { status },
                },
              ];
            });
          }
          break;
        }

        case "alert": {
          const alertData = msg.data as unknown as AlertData;
          setAlerts((prev) => [alertData, ...prev].slice(0, 20));
          break;
        }

        case "alert_state_change": {
          const stateData = msg.data as { id: string; status: string };
          setAlerts((prev) =>
            prev.map((a) =>
              a.id === stateData.id
                ? { ...a, status: stateData.status }
                : a,
            ),
          );
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
    },
    [finalizeTextSegment, updateGroupedMessage],
  );

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
    agentMode,
    alerts,
    budgetStatus,
    dismissAlert,
    acknowledgeAlert,
    handleServerMessage,
    addUserMessage,
  };
}
