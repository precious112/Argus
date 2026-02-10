"use client";

import { ChatContainer } from "@/components/chat/ChatContainer";

export default function Home() {
  return (
    <div className="flex h-full flex-col">
      <ChatContainer />
    </div>
  );
}
