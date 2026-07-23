"use client";

/** Conversation-list and transcript state for the chat workspace. */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  deleteChat,
  getChat,
  listChats,
  type ConversationSummary,
} from "@/lib/api";
import type { ChatMessage, Citation } from "@/lib/chatTypes";

export interface UseChatsOptions {
  accessToken: string | null;
  onUnauthorized: () => void;
}

export interface ChatsState {
  chats: ConversationSummary[];
  activeConversationId: string | null;
  threadId: string | undefined;
  messages: ChatMessage[];
  title: string;
  isConversationLoading: boolean;
  deletingConversationId: string | null;
  error: string | null;
  appendMessage: (message: ChatMessage) => void;
  updateAssistantMessage: (id: string, content: string, citations: Citation[]) => void;
  updateIdentity: (threadId: string, conversationId: string) => void;
  finishStream: (
    list: ConversationSummary[],
    conversationId: string | null,
    threadId: string | undefined,
  ) => void;
  refreshChats: () => Promise<ConversationSummary[]>;
  startNewConversation: () => void;
  selectConversation: (id: string) => Promise<void>;
  removeConversation: (id: string) => Promise<void>;
  clearError: () => void;
}

/** Own chat history, active-conversation loading, deletion, and transcript updates. */
export function useChats({ accessToken, onUnauthorized }: UseChatsOptions): ChatsState {
  const [chats, setChats] = useState<ConversationSummary[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [threadId, setThreadId] = useState<string | undefined>(undefined);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [title, setTitle] = useState("New chat");
  const [isConversationLoading, setIsConversationLoading] = useState(false);
  const [deletingConversationId, setDeletingConversationId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const selectionRequestRef = useRef(0);

  const handleError = useCallback(
    (caught: unknown, fallback: string) => {
      if (caught instanceof Error && caught.message === "unauthorized") {
        onUnauthorized();
        return;
      }
      setError(fallback);
    },
    [onUnauthorized],
  );

  const refreshChats = useCallback(async (): Promise<ConversationSummary[]> => {
    if (!accessToken) return [];
    try {
      const list = await listChats(accessToken);
      setChats(list);
      return list;
    } catch (caught) {
      handleError(caught, "Could not refresh conversations.");
      throw caught;
    }
  }, [accessToken, handleError]);

  useEffect(() => {
    if (!accessToken) return;

    let cancelled = false;
    void listChats(accessToken)
      .then((list) => {
        if (!cancelled) setChats(list);
      })
      .catch((caught: unknown) => {
        if (!cancelled) handleError(caught, "Could not load conversations.");
      });

    return () => {
      cancelled = true;
    };
  }, [accessToken, handleError]);

  const startNewConversation = useCallback(() => {
    selectionRequestRef.current += 1;
    setActiveConversationId(null);
    setThreadId(undefined);
    setMessages([]);
    setTitle("New chat");
    setIsConversationLoading(false);
    setError(null);
  }, []);

  const selectConversation = useCallback(
    async (id: string) => {
      if (!accessToken || id === activeConversationId) return;
      const requestId = selectionRequestRef.current + 1;
      selectionRequestRef.current = requestId;
      setError(null);
      setIsConversationLoading(true);
      try {
        const detail = await getChat(id, accessToken);
        if (requestId !== selectionRequestRef.current) return;
        setActiveConversationId(detail.id);
        setThreadId(detail.thread_id);
        setTitle(detail.title?.trim() || "Untitled conversation");
        setMessages(
          detail.messages.map((message, index) => ({
            id: `${detail.id}-${index}`,
            role: message.role,
            content: message.content,
          })),
        );
      } catch (caught) {
        if (requestId === selectionRequestRef.current) {
          handleError(caught, "Could not load conversation.");
        }
      } finally {
        if (requestId === selectionRequestRef.current) {
          setIsConversationLoading(false);
        }
      }
    },
    [accessToken, activeConversationId, handleError],
  );

  const removeConversation = useCallback(
    async (id: string) => {
      if (!accessToken || deletingConversationId) return;
      setDeletingConversationId(id);
      setError(null);
      try {
        await deleteChat(id, accessToken);
        setChats((current) => current.filter((chat) => chat.id !== id));
        if (id === activeConversationId) startNewConversation();
      } catch (caught) {
        handleError(caught, "Could not delete conversation.");
      } finally {
        setDeletingConversationId(null);
      }
    },
    [
      accessToken,
      activeConversationId,
      deletingConversationId,
      handleError,
      startNewConversation,
    ],
  );

  const appendMessage = useCallback((message: ChatMessage) => {
    setMessages((current) => [...current, message]);
  }, []);

  const updateAssistantMessage = useCallback(
    (id: string, content: string, citations: Citation[]) => {
      setMessages((current) => {
        const existing = current.some((message) => message.id === id);
        if (!existing) {
          return [...current, { id, role: "assistant", content, citations }];
        }
        return current.map((message) =>
          message.id === id ? { ...message, content, citations } : message,
        );
      });
    },
    [],
  );

  const updateIdentity = useCallback((nextThreadId: string, conversationId: string) => {
    setThreadId(nextThreadId);
    setActiveConversationId(conversationId);
  }, []);

  const finishStream = useCallback(
    (
      list: ConversationSummary[],
      conversationId: string | null,
      completedThreadId: string | undefined,
    ) => {
      setChats(list);
      const updated = conversationId
        ? list.find((chat) => chat.id === conversationId)
        : list.find((chat) => chat.thread_id === completedThreadId);
      if (updated?.title) setTitle(updated.title.trim() || "Untitled conversation");
      if (updated && !conversationId) setActiveConversationId(updated.id);
    },
    [],
  );

  const clearError = useCallback(() => setError(null), []);

  return {
    chats,
    activeConversationId,
    threadId,
    messages,
    title,
    isConversationLoading,
    deletingConversationId,
    error,
    appendMessage,
    updateAssistantMessage,
    updateIdentity,
    finishStream,
    refreshChats,
    startNewConversation,
    selectConversation,
    removeConversation,
    clearError,
  };
}
