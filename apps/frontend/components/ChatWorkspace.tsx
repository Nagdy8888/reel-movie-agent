"use client";

/** Responsive workspace composition for auth, conversations, streaming, and graph views. */

import {
  useCallback,
  useEffect,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from "react";
import type { User } from "@supabase/supabase-js";
import { useAnswerGraph } from "@/hooks/useAnswerGraph";
import { useAuthSession } from "@/hooks/useAuthSession";
import { useChats } from "@/hooks/useChats";
import { useChatStream } from "@/hooks/useChatStream";
import { groupChatsByRecency } from "@/lib/groupChats";
import { ChatInput } from "@/components/ChatInput";
import { ChatThread } from "@/components/ChatThread";
import { GraphCanvas } from "@/components/GraphCanvas";
import { MaterialIcon } from "@/components/MaterialIcon";
import { Sidebar } from "@/components/Sidebar";

const CHAT_PANE_MIN_WIDTH = 320;
const CHAT_PANE_MAX_WIDTH = 720;
const CHAT_PANE_DEFAULT_WIDTH = 440;
const CHAT_PANE_WIDTH_STORAGE_KEY = "reel-chat-pane-width";

type MobilePanel = "graph" | "chat";

/** Keep the persisted desktop chat width inside usable bounds. */
function clampChatPaneWidth(width: number): number {
  return Math.min(CHAT_PANE_MAX_WIDTH, Math.max(CHAT_PANE_MIN_WIDTH, width));
}

/** Derive a friendly visual name from Supabase profile metadata. */
function displayName(user: User | null): string {
  if (!user) return "Guest";
  const metadata = user.user_metadata as { full_name?: string } | undefined;
  return metadata?.full_name?.trim() || user.email?.split("@")[0] || "Cinephile";
}

/** Derive a compact fallback avatar label. */
function userInitial(user: User | null): string {
  return displayName(user).charAt(0).toUpperCase();
}

/** Three-pane desktop workspace with a tabbed small-viewport layout. */
export function ChatWorkspace() {
  const auth = useAuthSession();
  const chats = useChats({
    accessToken: auth.accessToken,
    onUnauthorized: auth.redirectToLogin,
  });
  const answerGraph = useAnswerGraph({
    accessToken: auth.accessToken,
    onUnauthorized: auth.redirectToLogin,
  });
  const chatStream = useChatStream({
    accessToken: auth.accessToken,
    threadId: chats.threadId,
    activeConversationId: chats.activeConversationId,
    appendMessage: chats.appendMessage,
    updateAssistantMessage: chats.updateAssistantMessage,
    updateIdentity: chats.updateIdentity,
    refreshChats: chats.refreshChats,
    finishStream: chats.finishStream,
    resetAnswer: answerGraph.resetAnswer,
    setSources: answerGraph.setSources,
    setAnswerGraph: answerGraph.setAnswerGraph,
    clearChatError: chats.clearError,
    onUnauthorized: auth.redirectToLogin,
  });

  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [mobilePanel, setMobilePanel] = useState<MobilePanel>("chat");
  const [chatPaneWidth, setChatPaneWidth] = useState(CHAT_PANE_DEFAULT_WIDTH);

  useEffect(() => {
    const savedWidth = Number(window.localStorage.getItem(CHAT_PANE_WIDTH_STORAGE_KEY));
    if (Number.isFinite(savedWidth)) {
      queueMicrotask(() => setChatPaneWidth(clampChatPaneWidth(savedWidth)));
    }

    const desktop = window.matchMedia("(min-width: 768px)");
    const syncSidebar = () => setSidebarOpen(desktop.matches);
    syncSidebar();
    desktop.addEventListener("change", syncSidebar);
    return () => desktop.removeEventListener("change", syncSidebar);
  }, []);

  const handleNewDiscovery = useCallback(() => {
    chatStream.abort();
    chats.startNewConversation();
    answerGraph.resetAnswer();
    chatStream.setInput("");
    chatStream.clearError();
    setMobilePanel("chat");
  }, [answerGraph, chatStream, chats]);

  const handleSelectConversation = useCallback(
    async (id: string) => {
      chatStream.abort();
      answerGraph.resetAnswer();
      await chats.selectConversation(id);
      if (window.matchMedia("(max-width: 767px)").matches) setSidebarOpen(false);
      setMobilePanel("chat");
    },
    [answerGraph, chatStream, chats],
  );

  const handleDeleteConversation = useCallback(
    (id: string) => {
      const conversation = chats.chats.find((chat) => chat.id === id);
      const title = conversation?.title?.trim() || "this conversation";
      if (!window.confirm(`Delete ${title}? This cannot be undone.`)) return;
      if (id === chats.activeConversationId) {
        chatStream.abort();
        answerGraph.resetAnswer();
      }
      void chats.removeConversation(id);
    },
    [answerGraph, chatStream, chats],
  );

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

  if (auth.isLoading) {
    return (
      <div
        className="h-dvh bg-canvas text-on-surface-variant flex items-center justify-center"
        role="status"
      >
        Loading your workspace…
      </div>
    );
  }

  const grouped = groupChatsByRecency(chats.chats);
  const error = auth.error ?? chats.error ?? chatStream.error;

  return (
    <div className="bg-surface-container-lowest text-on-surface h-dvh overflow-hidden flex flex-col font-body-lg">
      <nav className="md:hidden h-12 flex-shrink-0 border-b border-hairline bg-canvas flex items-center justify-between px-sm z-40">
        <button
          type="button"
          onClick={() => setSidebarOpen(true)}
          className="p-xs text-on-surface-variant"
          aria-label="Open conversation history"
        >
          <MaterialIcon name="menu" />
        </button>
        <div className="flex rounded-full border border-hairline bg-background p-1">
          {(["graph", "chat"] as const).map((panel) => (
            <button
              key={panel}
              type="button"
              onClick={() => setMobilePanel(panel)}
              aria-pressed={mobilePanel === panel}
              className={`rounded-full px-md py-1 font-label-caps text-label-caps capitalize ${
                mobilePanel === panel
                  ? "bg-primary-container/20 text-primary-container"
                  : "text-on-surface-variant"
              }`}
            >
              {panel}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={handleNewDiscovery}
          className="p-xs text-primary-container"
          aria-label="Start new discovery"
        >
          <MaterialIcon name="add" />
        </button>
      </nav>

      <div className="relative flex flex-1 min-h-0">
        {sidebarOpen && (
          <button
            type="button"
            className="md:hidden absolute inset-0 z-40 bg-black/55"
            onClick={() => setSidebarOpen(false)}
            aria-label="Close conversation history"
          />
        )}
        <Sidebar
          grouped={grouped}
          activeConversationId={chats.activeConversationId}
          userInitial={userInitial(auth.user)}
          userName={displayName(auth.user)}
          isOpen={sidebarOpen}
          onToggle={() => setSidebarOpen(false)}
          onNewDiscovery={handleNewDiscovery}
          onSelectConversation={(id) => void handleSelectConversation(id)}
          onDeleteConversation={handleDeleteConversation}
          deletingConversationId={chats.deletingConversationId}
          onSignOut={() => {
            chatStream.abort();
            void auth.signOut();
          }}
        />
        <GraphCanvas
          answerGraph={answerGraph.graph}
          fullGraph={answerGraph.fullGraph}
          fullGraphStatus={answerGraph.fullGraphStatus}
          mode={answerGraph.graphMode}
          sources={answerGraph.sources}
          selectedNodeId={answerGraph.selectedGraphNodeId}
          onModeChange={answerGraph.changeMode}
          onRetryFullGraph={answerGraph.retryFullGraph}
          onSelectNode={answerGraph.selectNode}
          className={mobilePanel === "graph" ? "flex" : "hidden md:flex"}
        />
        <div
          role="separator"
          aria-label="Resize chat panel"
          aria-orientation="vertical"
          onPointerDown={handleResizeStart}
          className="hidden md:block w-1.5 h-full cursor-col-resize bg-hairline hover:bg-primary-container/70 active:bg-primary-container transition-colors flex-shrink-0 z-30"
        />
        <aside
          className={`${mobilePanel === "chat" ? "flex" : "hidden"} md:flex h-full w-full md:w-[var(--chat-pane-width)] bg-background md:border-l border-hairline flex-col flex-shrink-0 relative z-30 min-w-0`}
          style={{ "--chat-pane-width": `${chatPaneWidth}px` } as CSSProperties}
          aria-label="Chat panel"
        >
          <header className="h-[64px] border-b border-hairline flex items-center justify-between px-md glass-panel flex-shrink-0">
            <div className="flex items-center gap-md min-w-0 flex-1">
              {!sidebarOpen && (
                <button
                  type="button"
                  onClick={() => setSidebarOpen(true)}
                  className="hidden md:block text-on-surface-variant hover:text-primary-container transition-colors flex-shrink-0"
                  aria-label="Open sidebar"
                >
                  <MaterialIcon name="menu" />
                </button>
              )}
              <h1 className="font-headline-lg text-headline-lg text-on-surface truncate pr-md">
                {chats.title}
              </h1>
            </div>
            <div className="hidden xl:flex items-center gap-2 px-3 py-1 rounded-full border border-primary-container/30 bg-primary-container/10">
              <MaterialIcon name="psychology" className="text-primary-container" size={14} />
              <span className="font-label-caps text-label-caps text-primary-container">
                GPT-4 Movie Graph
              </span>
            </div>
          </header>
          {error && (
            <div
              role="alert"
              className="absolute top-[72px] left-md right-md z-30 bg-error-container text-on-error-container px-md py-sm rounded-lg font-body-sm text-body-sm"
            >
              {error}
            </div>
          )}
          {chats.isConversationLoading ? (
            <div
              className="flex-1 min-h-0 flex items-center justify-center text-on-surface-variant"
              role="status"
            >
              Loading conversation…
            </div>
          ) : (
            <ChatThread
              messages={chats.messages}
              isThinking={chatStream.isThinking}
              selectedCitationId={answerGraph.selectedGraphNodeId}
              onCitationSelect={answerGraph.selectCitation}
            />
          )}
          <ChatInput
            value={chatStream.input}
            onChange={chatStream.setInput}
            onSend={() => void chatStream.send()}
            disabled={chatStream.isStreaming || !auth.accessToken || chats.isConversationLoading}
          />
        </aside>
      </div>
    </div>
  );
}
