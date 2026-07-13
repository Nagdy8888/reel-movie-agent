"use client";

import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { useRouter } from "next/navigation";
import type { User } from "@supabase/supabase-js";
import { supabase } from "@/lib/supabaseClient";
import {
  getChat,
  getFullGraph,
  listChats,
  streamChat,
  type ConversationSummary,
  type GraphData,
  type SourceSummary,
} from "@/lib/api";
import { groupChatsByRecency } from "@/lib/groupChats";
import { Sidebar } from "@/components/Sidebar";
import { ChatThread, type ChatMessage } from "@/components/ChatThread";
import { ChatInput } from "@/components/ChatInput";
import { GraphCanvas } from "@/components/GraphCanvas";
import { MaterialIcon } from "@/components/MaterialIcon";

const CHAT_PANE_MIN_WIDTH = 320;
const CHAT_PANE_MAX_WIDTH = 720;
const CHAT_PANE_DEFAULT_WIDTH = 440;
const CHAT_PANE_WIDTH_STORAGE_KEY = "reel-chat-pane-width";
const FULL_GRAPH_LOAD_ATTEMPTS = 3;
const FULL_GRAPH_RETRY_DELAY_MS = 1_000;

function clampChatPaneWidth(width: number): number {
  return Math.min(CHAT_PANE_MAX_WIDTH, Math.max(CHAT_PANE_MIN_WIDTH, width));
}

function displayName(user: User | null): string {
  if (!user) return "Guest";
  const meta = user.user_metadata as { full_name?: string } | undefined;
  return meta?.full_name?.trim() || user.email?.split("@")[0] || "Cinephile";
}

function userInitial(user: User | null): string {
  const name = displayName(user);
  return name.charAt(0).toUpperCase();
}

/** Three-pane chat workspace wired to the backend SSE stream. */
export function ChatWorkspace() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [chats, setChats] = useState<ConversationSummary[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [threadId, setThreadId] = useState<string | undefined>(undefined);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [title, setTitle] = useState<string>("New chat");
  const [input, setInput] = useState("");
  const [isThinking, setIsThinking] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sources, setSources] = useState<SourceSummary[]>([]);
  const [graph, setGraph] = useState<GraphData>({ nodes: [], links: [] });
  const [fullGraph, setFullGraph] = useState<GraphData>({ nodes: [], links: [] });
  const [graphLoading, setGraphLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [chatPaneWidth, setChatPaneWidth] = useState(CHAT_PANE_DEFAULT_WIDTH);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const savedWidth = Number(window.localStorage.getItem(CHAT_PANE_WIDTH_STORAGE_KEY));
    if (!Number.isFinite(savedWidth)) return;
    queueMicrotask(() => setChatPaneWidth(clampChatPaneWidth(savedWidth)));
  }, []);

  const refreshChats = useCallback(async (token: string) => {
    try {
      const list = await listChats(token);
      setChats(list);
    } catch (err) {
      if (err instanceof Error && err.message === "unauthorized") {
        router.replace("/login");
      }
    }
  }, [router]);

  useEffect(() => {
    let mounted = true;

    const init = async () => {
      const {
        data: { session },
      } = await supabase.auth.getSession();
      if (!session) {
        router.replace("/login");
        return;
      }
      if (!mounted) return;
      setUser(session.user);
      setAccessToken(session.access_token);
      await refreshChats(session.access_token);
    };

    void init();

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      if (!session) {
        router.replace("/login");
        return;
      }
      setUser(session.user);
      setAccessToken(session.access_token);
    });

    return () => {
      mounted = false;
      subscription.unsubscribe();
      abortRef.current?.abort();
    };
  }, [router, refreshChats]);

  useEffect(() => {
    if (!accessToken) return;
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) setGraphLoading(true);
    });
    const loadGraph = async () => {
      try {
        for (let attempt = 0; attempt < FULL_GRAPH_LOAD_ATTEMPTS; attempt += 1) {
          try {
            const loadedGraph = await getFullGraph(accessToken);
            if (loadedGraph.nodes.length > 0 || attempt === FULL_GRAPH_LOAD_ATTEMPTS - 1) {
              if (!cancelled) setFullGraph(loadedGraph);
              return;
            }
          } catch (err) {
            if (err instanceof Error && err.message === "unauthorized") {
              router.replace("/login");
              return;
            }
          }

          await new Promise((resolve) => window.setTimeout(resolve, FULL_GRAPH_RETRY_DELAY_MS));
        }
      } finally {
        if (!cancelled) setGraphLoading(false);
      }
    };

    void loadGraph();
    return () => {
      cancelled = true;
    };
  }, [accessToken, router]);

  const handleNewDiscovery = () => {
    abortRef.current?.abort();
    setActiveConversationId(null);
    setThreadId(undefined);
    setMessages([]);
    setTitle("New chat");
    setInput("");
    setIsThinking(false);
    setIsStreaming(false);
    setError(null);
    setSources([]);
    setGraph({ nodes: [], links: [] });
  };

  const handleSelectConversation = async (id: string) => {
    if (!accessToken) return;
    abortRef.current?.abort();
    setError(null);
    setSources([]);
    setGraph({ nodes: [], links: [] });
    try {
      const detail = await getChat(id, accessToken);
      setActiveConversationId(detail.id);
      setThreadId(detail.thread_id);
      setTitle(detail.title?.trim() || "Untitled conversation");
      setMessages(
        detail.messages.map((m, i) => ({
          id: `${detail.id}-${i}`,
          role: m.role,
          content: m.content,
        })),
      );
      setIsThinking(false);
      setIsStreaming(false);
    } catch (err) {
      if (err instanceof Error && err.message === "unauthorized") {
        router.replace("/login");
      } else {
        setError("Could not load conversation.");
      }
    }
  };

  const handleSend = async () => {
    const text = input.trim();
    if (!text || !accessToken || isStreaming) return;

    setError(null);
    setInput("");
    setSources([]);
    setGraph({ nodes: [], links: [] });
    const userMsgId = `user-${Date.now()}`;
    const assistantMsgId = `assistant-${Date.now()}`;
    setMessages((prev) => [...prev, { id: userMsgId, role: "user", content: text }]);
    setIsThinking(true);
    setIsStreaming(true);

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    let assistantText = "";
    let gotFirstToken = false;
    let currentSources: SourceSummary[] = [];
    let currentConversationId = activeConversationId;
    let currentThreadId = threadId;

    const citationsFromSources = (items: SourceSummary[]) =>
      items.map((source, index) => ({
        index: index + 1,
        label: source.title,
      }));

    try {
      for await (const event of streamChat(text, accessToken, threadId, controller.signal)) {
        if (event.type === "meta") {
          currentThreadId = event.thread_id;
          currentConversationId = event.conversation_id;
          setThreadId(event.thread_id);
          setActiveConversationId(event.conversation_id);
        } else if (event.type === "sources") {
          currentSources = event.sources;
          setSources(event.sources);
          if (gotFirstToken) {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantMsgId
                  ? { ...m, citations: citationsFromSources(event.sources) }
                  : m,
              ),
            );
          }
        } else if (event.type === "graph") {
          setGraph(event.graph);
        } else if (event.type === "token") {
          if (!gotFirstToken) {
            gotFirstToken = true;
            setIsThinking(false);
            setMessages((prev) => [
              ...prev,
              {
                id: assistantMsgId,
                role: "assistant",
                content: event.text,
                citations: citationsFromSources(currentSources),
              },
            ]);
            assistantText = event.text;
          } else {
            assistantText += event.text;
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantMsgId
                  ? {
                      ...m,
                      content: assistantText,
                      citations: citationsFromSources(currentSources),
                    }
                  : m,
              ),
            );
          }
        } else if (event.type === "done") {
          break;
        }
      }
      const list = await listChats(accessToken);
      setChats(list);
      const updated = currentConversationId
        ? list.find((c) => c.id === currentConversationId)
        : list.find((c) => c.thread_id === currentThreadId);
      if (updated?.title) setTitle(updated.title.trim() || "Untitled conversation");
      if (updated && !currentConversationId) {
        setActiveConversationId(updated.id);
      }
    } catch (err) {
      if (controller.signal.aborted) return;
      if (err instanceof Error) {
        if (err.message === "unauthorized") {
          router.replace("/login");
          return;
        }
        if (err.message === "rate_limited") {
          setError("You're sending messages too quickly. Please slow down.");
        } else {
          setError("Something went wrong. Please try again.");
        }
      }
      setIsThinking(false);
    } finally {
      setIsStreaming(false);
    }
  };

  const handleResizeStart = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      const startX = event.clientX;
      const startWidth = chatPaneWidth;
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";

      const handlePointerMove = (moveEvent: PointerEvent) => {
        const nextWidth = clampChatPaneWidth(startWidth + startX - moveEvent.clientX);
        setChatPaneWidth(nextWidth);
        window.localStorage.setItem(CHAT_PANE_WIDTH_STORAGE_KEY, String(nextWidth));
      };

      const handlePointerUp = () => {
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
        window.removeEventListener("pointermove", handlePointerMove);
        window.removeEventListener("pointerup", handlePointerUp);
      };

      window.addEventListener("pointermove", handlePointerMove);
      window.addEventListener("pointerup", handlePointerUp);
    },
    [chatPaneWidth],
  );

  const grouped = groupChatsByRecency(chats);

  return (
    <div className="bg-surface-container-lowest text-on-surface h-screen overflow-hidden flex font-body-lg">
      <Sidebar
        grouped={grouped}
        activeConversationId={activeConversationId}
        userInitial={userInitial(user)}
        userName={displayName(user)}
        isOpen={sidebarOpen}
        onToggle={() => setSidebarOpen(false)}
        onNewDiscovery={handleNewDiscovery}
        onSelectConversation={handleSelectConversation}
      />
      <GraphCanvas fullGraph={fullGraph} highlight={graph} sources={sources} loading={graphLoading} />
      <div
        role="separator"
        aria-label="Resize chat panel"
        aria-orientation="vertical"
        onPointerDown={handleResizeStart}
        className="w-1.5 h-full cursor-col-resize bg-hairline hover:bg-primary-container/70 active:bg-primary-container transition-colors flex-shrink-0 z-40"
      />
      <aside
        className="h-full bg-background border-l border-hairline flex flex-col flex-shrink-0 relative z-30 min-w-0"
        style={{ width: chatPaneWidth }}
      >
        <header className="h-[64px] border-b border-hairline flex items-center justify-between px-md glass-panel flex-shrink-0">
          <div className="flex items-center gap-md min-w-0 flex-1">
            {!sidebarOpen && (
              <button
                type="button"
                onClick={() => setSidebarOpen(true)}
                className="text-on-surface-variant hover:text-primary-container transition-colors flex-shrink-0"
                aria-label="Open sidebar"
              >
                <MaterialIcon name="menu" />
              </button>
            )}
            <h1 className="font-headline-lg text-headline-lg text-on-surface truncate pr-md">{title}</h1>
          </div>
          <div className="hidden xl:flex items-center gap-2 px-3 py-1 rounded-full border border-primary-container/30 bg-primary-container/10">
            <MaterialIcon name="psychology" className="text-primary-container" size={14} />
            <span className="font-label-caps text-label-caps text-primary-container">
              GPT-4 Movie Graph
            </span>
          </div>
        </header>
        {error && (
          <div className="absolute top-[72px] left-md right-md z-30 bg-error-container text-on-error-container px-md py-sm rounded-lg font-body-sm text-body-sm">
            {error}
          </div>
        )}
        <ChatThread messages={messages} isThinking={isThinking} />
        <ChatInput
          value={input}
          onChange={setInput}
          onSend={() => void handleSend()}
          disabled={isStreaming || !accessToken}
        />
      </aside>
    </div>
  );
}
