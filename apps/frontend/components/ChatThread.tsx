"use client";

import { useEffect, useRef } from "react";
import type { ChatMessage } from "@/lib/chatTypes";
import { MessageBubble } from "./MessageBubble";
import { ThinkingIndicator } from "./ThinkingIndicator";

export interface ChatThreadProps {
  messages: ChatMessage[];
  isThinking: boolean;
  selectedCitationId: string | null;
  onCitationSelect: (id: string) => void;
}

/** Scrollable list of chat messages. */
export function ChatThread({
  messages,
  isThinking,
  selectedCitationId,
  onCitationSelect,
}: ChatThreadProps) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [isThinking, messages]);

  return (
    <div
      className="flex-1 min-h-0 overflow-y-auto thin-scrollbar p-md flex flex-col gap-lg w-full"
      aria-live="polite"
      aria-relevant="additions text"
      aria-busy={isThinking}
      aria-label="Conversation transcript"
    >
      {messages.map((msg) => (
        <MessageBubble
          key={msg.id}
          role={msg.role}
          content={msg.content}
          citations={msg.citations}
          selectedCitationId={selectedCitationId}
          onCitationSelect={onCitationSelect}
        />
      ))}
      {isThinking && <ThinkingIndicator />}
      <div ref={endRef} aria-hidden="true" />
    </div>
  );
}
