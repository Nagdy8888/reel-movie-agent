/** Shared view models for the chat transcript. */

/** One source citation attached to an assistant answer. */
export interface Citation {
  id: string;
  index: number;
  label: string;
}

/** One rendered user or assistant message. */
export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
}
