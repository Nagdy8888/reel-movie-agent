import type { ConversationSummary } from "@/lib/api";
import type { GroupedChats } from "@/lib/groupChats";
import { MaterialIcon } from "./MaterialIcon";

export interface SidebarProps {
  grouped: GroupedChats;
  activeConversationId: string | null;
  userInitial: string;
  userName: string;
  isOpen: boolean;
  onToggle: () => void;
  onNewDiscovery: () => void;
  onSelectConversation: (id: string) => void;
}

interface ConversationItemProps {
  chat: ConversationSummary;
  isActive: boolean;
  onSelect: () => void;
}

function ConversationItem({ chat, isActive, onSelect }: ConversationItemProps) {
  const title = chat.title?.trim() || "Untitled conversation";
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        className={`w-full text-left px-sm py-sm rounded-md flex items-center gap-sm transition-colors ${
          isActive
            ? "bg-surface-container/50 text-primary-container border border-hairline"
            : "hover:bg-surface-container/30 text-on-surface-variant"
        }`}
      >
        <MaterialIcon name="chat_bubble_outline" size={16} />
        <span className="truncate font-body-sm text-body-sm">{title}</span>
      </button>
    </li>
  );
}

function ConversationGroup({
  label,
  chats,
  activeConversationId,
  onSelectConversation,
}: {
  label: string;
  chats: ConversationSummary[];
  activeConversationId: string | null;
  onSelectConversation: (id: string) => void;
}) {
  if (chats.length === 0) return null;
  return (
    <div className="mb-lg mt-md">
      <h3 className="font-label-caps text-label-caps text-on-surface-variant mb-sm px-sm">{label}</h3>
      <ul className="space-y-xs">
        {chats.map((chat) => (
          <ConversationItem
            key={chat.id}
            chat={chat}
            isActive={chat.id === activeConversationId}
            onSelect={() => onSelectConversation(chat.id)}
          />
        ))}
      </ul>
    </div>
  );
}

/** Left sidebar with conversation history and user footer. */
export function Sidebar({
  grouped,
  activeConversationId,
  userInitial,
  userName,
  isOpen,
  onToggle,
  onNewDiscovery,
  onSelectConversation,
}: SidebarProps) {
  const hasChats = grouped.today.length > 0 || grouped.previous7Days.length > 0;

  return (
    <aside
      className={`h-full bg-canvas border-r border-hairline flex flex-col flex-shrink-0 overflow-hidden transition-[width,opacity,border-color] duration-300 ease-in-out ${
        isOpen ? "w-[260px] opacity-100" : "w-0 opacity-0 border-r-transparent pointer-events-none"
      }`}
      aria-hidden={!isOpen}
    >
      <div className="w-[260px] min-w-[260px] h-full flex flex-col">
      <div className="p-lg flex items-center justify-between">
        <span className="font-display-md text-display-md text-primary-container text-glow tracking-tight">
          Reel
        </span>
        <button
          type="button"
          onClick={onToggle}
          className="text-on-surface-variant hover:text-primary-container transition-colors"
          aria-label="Collapse sidebar"
        >
          <MaterialIcon name="menu" />
        </button>
      </div>
      <div className="px-md mb-md">
        <button
          type="button"
          onClick={onNewDiscovery}
          className="w-full bg-primary-container text-on-primary-container font-title-md text-title-md py-sm rounded-lg flex items-center justify-center gap-sm hover:brightness-110 transition-all duration-300"
        >
          <MaterialIcon name="add" size={20} />
          New Discovery
        </button>
      </div>
      <div className="flex-1 overflow-y-auto thin-scrollbar px-md">
        {!hasChats && (
          <p className="font-body-sm text-body-sm text-on-surface-variant px-sm mt-md">
            No conversations yet. Start a new discovery!
          </p>
        )}
        <ConversationGroup
          label="Today"
          chats={grouped.today}
          activeConversationId={activeConversationId}
          onSelectConversation={onSelectConversation}
        />
        <ConversationGroup
          label="Previous 7 Days"
          chats={grouped.previous7Days}
          activeConversationId={activeConversationId}
          onSelectConversation={onSelectConversation}
        />
      </div>
      <div className="p-md border-t border-hairline mt-auto">
        <button
          type="button"
          className="flex items-center gap-md w-full hover:bg-surface-container/30 p-sm rounded-lg transition-colors"
        >
          <div className="w-8 h-8 rounded-full bg-surface-variant flex items-center justify-center overflow-hidden border border-hairline">
            <span className="font-title-md text-body-sm text-primary-container">{userInitial}</span>
          </div>
          <div className="flex-1 text-left">
            <div className="font-title-md text-body-sm">{userName}</div>
            <div className="font-body-sm text-[12px] text-on-surface-variant">Settings</div>
          </div>
          <MaterialIcon name="settings" className="text-on-surface-variant" size={20} />
        </button>
      </div>
      </div>
    </aside>
  );
}
