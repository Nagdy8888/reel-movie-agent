"use client";

/** Streaming chat request lifecycle and input state. */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  streamChat,
  type ConversationSummary,
  type GraphData,
  type SourceSummary,
} from "@/lib/api";
import type { ChatMessage, Citation } from "@/lib/chatTypes";

export interface UseChatStreamOptions {
  accessToken: string | null;
  threadId: string | undefined;
  activeConversationId: string | null;
  appendMessage: (message: ChatMessage) => void;
  updateAssistantMessage: (id: string, content: string, citations: Citation[]) => void;
  updateIdentity: (threadId: string, conversationId: string) => void;
  refreshChats: () => Promise<ConversationSummary[]>;
  finishStream: (
    list: ConversationSummary[],
    conversationId: string | null,
    threadId: string | undefined,
  ) => void;
  resetAnswer: () => void;
  setSources: (sources: SourceSummary[]) => void;
  setAnswerGraph: (graph: GraphData) => void;
  clearChatError: () => void;
  onUnauthorized: () => void;
}

export interface ChatStreamState {
  input: string;
  isThinking: boolean;
  isStreaming: boolean;
  error: string | null;
  setInput: (value: string) => void;
  send: () => Promise<void>;
  abort: () => void;
  clearError: () => void;
}

/** Convert source cards into stable, one-based transcript citations. */
function citationsFromSources(items: SourceSummary[]): Citation[] {
  return items.map((source, index) => ({
    id: source.id,
    index: index + 1,
    label: source.title,
  }));
}

/** Stream one turn while preserving partial answers and isolating cancellation. */
export function useChatStream({
  accessToken,
  threadId,
  activeConversationId,
  appendMessage,
  updateAssistantMessage,
  updateIdentity,
  refreshChats,
  finishStream,
  resetAnswer,
  setSources,
  setAnswerGraph,
  clearChatError,
  onUnauthorized,
}: UseChatStreamOptions): ChatStreamState {
  const [input, setInput] = useState("");
  const [isThinking, setIsThinking] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const abort = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsThinking(false);
    setIsStreaming(false);
  }, []);

  useEffect(() => abort, [abort]);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || !accessToken || isStreaming) return;

    setError(null);
    clearChatError();
    setInput("");
    resetAnswer();

    const now = Date.now();
    const userMessageId = `user-${now}`;
    const assistantMessageId = `assistant-${now}`;
    appendMessage({ id: userMessageId, role: "user", content: text });
    setIsThinking(true);
    setIsStreaming(true);

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    let assistantText = "";
    let currentSources: SourceSummary[] = [];
    let currentConversationId = activeConversationId;
    let currentThreadId = threadId;

    try {
      for await (const event of streamChat(
        text,
        accessToken,
        threadId,
        controller.signal,
      )) {
        if (event.type === "meta") {
          currentThreadId = event.thread_id;
          currentConversationId = event.conversation_id;
          updateIdentity(event.thread_id, event.conversation_id);
        } else if (event.type === "sources") {
          currentSources = event.sources;
          setSources(event.sources);
          if (assistantText) {
            updateAssistantMessage(
              assistantMessageId,
              assistantText,
              citationsFromSources(event.sources),
            );
          }
        } else if (event.type === "graph") {
          setAnswerGraph(event.graph);
        } else if (event.type === "token") {
          assistantText += event.text;
          setIsThinking(false);
          updateAssistantMessage(
            assistantMessageId,
            assistantText,
            citationsFromSources(currentSources),
          );
        } else if (event.type === "error") {
          throw new Error(event.code);
        } else if (event.type === "done") {
          break;
        }
      }

      try {
        const list = await refreshChats();
        finishStream(list, currentConversationId, currentThreadId);
      } catch {
        // The answer remains usable; useChats surfaces the independent list refresh error.
      }
    } catch (caught) {
      if (controller.signal.aborted) return;
      if (caught instanceof Error && caught.message === "unauthorized") {
        onUnauthorized();
        return;
      }
      if (caught instanceof Error && caught.message === "rate_limited") {
        setError("You're sending messages too quickly. Please slow down.");
      } else {
        setError("Something went wrong. Please try again.");
      }
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null;
        setIsThinking(false);
        setIsStreaming(false);
      }
    }
  }, [
    accessToken,
    activeConversationId,
    appendMessage,
    clearChatError,
    finishStream,
    input,
    isStreaming,
    onUnauthorized,
    refreshChats,
    resetAnswer,
    setAnswerGraph,
    setSources,
    threadId,
    updateAssistantMessage,
    updateIdentity,
  ]);

  const clearError = useCallback(() => setError(null), []);

  return { input, isThinking, isStreaming, error, setInput, send, abort, clearError };
}
