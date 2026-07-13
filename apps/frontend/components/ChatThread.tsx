import type { MessageBubbleProps } from "./MessageBubble";
import { MessageBubble } from "./MessageBubble";
import { ThinkingIndicator } from "./ThinkingIndicator";

export interface ChatMessage
  extends Omit<MessageBubbleProps, "citations" | "selectedCitationId" | "onCitationSelect"> {
  id: string;
  citations?: MessageBubbleProps["citations"];
}

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
  return (
    <div className="flex-1 min-h-0 overflow-y-auto thin-scrollbar p-md flex flex-col gap-lg w-full">
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
    </div>
  );
}
