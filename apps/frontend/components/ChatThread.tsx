import type { MessageBubbleProps } from "./MessageBubble";
import { MessageBubble } from "./MessageBubble";
import { ThinkingIndicator } from "./ThinkingIndicator";

export interface ChatMessage extends Omit<MessageBubbleProps, "citations"> {
  id: string;
  citations?: MessageBubbleProps["citations"];
}

export interface ChatThreadProps {
  messages: ChatMessage[];
  isThinking: boolean;
}

/** Scrollable list of chat messages. */
export function ChatThread({ messages, isThinking }: ChatThreadProps) {
  return (
    <div className="flex-1 min-h-0 overflow-y-auto thin-scrollbar p-md flex flex-col gap-lg w-full">
      {messages.map((msg) => (
        <MessageBubble
          key={msg.id}
          role={msg.role}
          content={msg.content}
          citations={msg.citations}
        />
      ))}
      {isThinking && <ThinkingIndicator />}
    </div>
  );
}
