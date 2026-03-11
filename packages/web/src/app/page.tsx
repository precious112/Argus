"use client";

import { ChatContainer } from "@/components/chat/ChatContainer";
import { UpgradePopup } from "@/components/system/UpgradePopup";

export default function Home() {
  return (
    <div className="flex h-full flex-col">
      <ChatContainer />
      <UpgradePopup />
    </div>
  );
}
