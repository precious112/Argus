"use client";

import { ChatContainer } from "@/components/chat/ChatContainer";
import { StatusBar } from "@/components/system/StatusBar";

export default function Home() {
  return (
    <div className="flex h-full flex-col">
      <StatusBar />
      <ChatContainer />
    </div>
  );
}
