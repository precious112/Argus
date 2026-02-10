"use client";

import { useCallback, useState } from "react";
import type { ActionRequest, ClientMessage } from "@/lib/protocol";

export interface PendingAction {
  request: ActionRequest;
  resolved: boolean;
}

export function useActions(
  send: (message: ClientMessage) => void,
) {
  const [pendingActions, setPendingActions] = useState<PendingAction[]>([]);

  const addPendingAction = useCallback((request: ActionRequest) => {
    setPendingActions((prev) => [
      ...prev,
      { request, resolved: false },
    ]);
  }, []);

  const approveAction = useCallback(
    (actionId: string) => {
      send({
        type: "action_response",
        id: actionId,
        data: { action_id: actionId, approved: true },
      });
      setPendingActions((prev) =>
        prev.map((a) =>
          a.request.id === actionId ? { ...a, resolved: true } : a,
        ),
      );
    },
    [send],
  );

  const rejectAction = useCallback(
    (actionId: string) => {
      send({
        type: "action_response",
        id: actionId,
        data: { action_id: actionId, approved: false },
      });
      setPendingActions((prev) =>
        prev.map((a) =>
          a.request.id === actionId ? { ...a, resolved: true } : a,
        ),
      );
    },
    [send],
  );

  const resolveAction = useCallback((actionId: string) => {
    setPendingActions((prev) =>
      prev.map((a) =>
        a.request.id === actionId ? { ...a, resolved: true } : a,
      ),
    );
  }, []);

  return {
    pendingActions,
    addPendingAction,
    approveAction,
    rejectAction,
    resolveAction,
  };
}
