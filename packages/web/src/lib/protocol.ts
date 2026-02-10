/**
 * WebSocket chat protocol type definitions.
 * Mirrors packages/agent/src/argus_agent/api/protocol.py
 */

// --- Client → Server ---

export type ClientMessageType =
  | "user_message"
  | "action_response"
  | "cancel"
  | "ping";

export interface ClientMessage {
  type: ClientMessageType;
  id: string;
  data: Record<string, unknown>;
}

// --- Server → Client ---

export type ServerMessageType =
  | "connected"
  | "system_status"
  | "thinking_start"
  | "thinking_end"
  | "tool_call"
  | "tool_result"
  | "assistant_message_start"
  | "assistant_message_delta"
  | "assistant_message_end"
  | "action_request"
  | "action_executing"
  | "action_complete"
  | "alert"
  | "investigation_start"
  | "investigation_update"
  | "investigation_end"
  | "budget_update"
  | "error"
  | "pong";

export interface ServerMessage {
  type: ServerMessageType;
  timestamp: string;
  data: Record<string, unknown>;
}

export type ToolResultDisplayType =
  | "log_viewer"
  | "metrics_chart"
  | "process_table"
  | "json_tree"
  | "code_block"
  | "diff_view"
  | "table"
  | "text";

export interface ActionRequest {
  id: string;
  tool: string;
  description: string;
  command: string[] | string;
  risk_level: "READ_ONLY" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  reversible: boolean;
  requires_password: boolean;
}

export interface AlertData {
  id: string;
  severity: string;
  title: string;
  summary: string;
  source: string;
  timestamp: string;
  investigation_thread_id?: string;
}

export interface BudgetStatus {
  hourly_used: number;
  hourly_limit: number;
  hourly_pct: number;
  daily_used: number;
  daily_limit: number;
  daily_pct: number;
  total_tokens: number;
  total_requests: number;
}

export interface InvestigationData {
  investigation_id: string;
  trigger?: string;
  severity?: string;
  content?: string;
  summary?: string;
  tokens_used?: number;
  type?: string;
}
