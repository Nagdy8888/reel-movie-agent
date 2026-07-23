import type { ConversationSummary } from "./api";

export interface GroupedChats {
  today: ConversationSummary[];
  previous7Days: ConversationSummary[];
  older: ConversationSummary[];
}

/** Group conversations by recency using ``updated_at``. */
export function groupChatsByRecency(chats: ConversationSummary[]): GroupedChats {
  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const weekAgo = new Date(todayStart);
  weekAgo.setDate(weekAgo.getDate() - 7);

  const today: ConversationSummary[] = [];
  const previous7Days: ConversationSummary[] = [];
  const older: ConversationSummary[] = [];

  for (const chat of chats) {
    const updated = new Date(chat.updated_at);
    if (updated >= todayStart) {
      today.push(chat);
    } else if (updated >= weekAgo) {
      previous7Days.push(chat);
    } else {
      older.push(chat);
    }
  }

  return { today, previous7Days, older };
}
