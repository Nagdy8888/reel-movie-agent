const API = process.env.NEXT_PUBLIC_API_URL!;

/** Shapes returned by the backend (mirror apps/backend/src/api/schemas.py). */
export interface ConversationSummary {
  id: string;
  thread_id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
}

export interface MessageOut {
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  messages: MessageOut[];
}

export interface SourceSummary {
  id: string;
  title: string;
  subtitle?: string | null;
  year?: string | null;
  poster_url?: string | null;
  tags: string[];
}

export interface GraphNode {
  id: string;
  label: string;
  type: "Movie" | "Person" | string;
}

export interface GraphLink {
  source: string;
  target: string;
  label: string;
}

export interface GraphData {
  nodes: GraphNode[];
  links: GraphLink[];
}

/** Discriminated union of SSE events emitted by POST /chat. */
export type ChatEvent =
  | { type: "meta"; thread_id: string; conversation_id: string }
  | { type: "token"; text: string }
  | { type: "sources"; sources: SourceSummary[] }
  | { type: "graph"; graph: GraphData }
  | { type: "done" };

/** Stream an answer from POST /chat, decoding the meta/token/done SSE frames. */
export async function* streamChat(
  message: string,
  token: string,
  threadId?: string,
  signal?: AbortSignal,
): AsyncGenerator<ChatEvent> {
  const res = await fetch(`${API}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ message, thread_id: threadId }),
    signal,
  });
  if (res.status === 401 || res.status === 403) throw new Error("unauthorized");
  if (res.status === 429) throw new Error("rate_limited");
  if (!res.ok || !res.body) throw new Error(`chat failed: ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      let eventName = "message";
      let dataLine = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLine = line.slice(5).trim();
      }
      if (!dataLine) continue;
      const payload = JSON.parse(dataLine) as Record<string, unknown>;
      if (eventName === "meta") {
        yield {
          type: "meta",
          thread_id: String(payload.thread_id),
          conversation_id: String(payload.conversation_id),
        };
      } else if (eventName === "sources") {
        yield {
          type: "sources",
          sources: (payload.sources as SourceSummary[]) ?? [],
        };
      } else if (eventName === "graph") {
        const graph = payload as unknown as GraphData;
        yield {
          type: "graph",
          graph: {
            nodes: graph.nodes ?? [],
            links: graph.links ?? [],
          },
        };
      } else if (eventName === "done") {
        yield { type: "done" };
      } else if (typeof payload.token === "string") {
        yield { type: "token", text: payload.token };
      }
    }
  }
}

/** List the current user's conversations (newest first). */
export async function listChats(token: string): Promise<ConversationSummary[]> {
  const res = await fetch(`${API}/chats`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (res.status === 401 || res.status === 403) throw new Error("unauthorized");
  if (!res.ok) throw new Error(`listChats failed: ${res.status}`);
  return res.json();
}

/** Fetch one conversation with its messages. */
export async function getChat(id: string, token: string): Promise<ConversationDetail> {
  const res = await fetch(`${API}/chats/${id}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (res.status === 401 || res.status === 403) throw new Error("unauthorized");
  if (!res.ok) throw new Error(`getChat failed: ${res.status}`);
  return res.json();
}

/** Fetch the full movie knowledge graph used by the main canvas. */
export async function getFullGraph(token: string): Promise<GraphData> {
  const res = await fetch(`${API}/graph`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (res.status === 401 || res.status === 403) throw new Error("unauthorized");
  if (!res.ok) throw new Error(`getFullGraph failed: ${res.status}`);
  const graph = (await res.json()) as GraphData;
  return {
    nodes: graph.nodes ?? [],
    links: graph.links ?? [],
  };
}

/** Delete a conversation. */
export async function deleteChat(id: string, token: string): Promise<void> {
  const res = await fetch(`${API}/chats/${id}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (res.status === 401 || res.status === 403) throw new Error("unauthorized");
  if (!res.ok && res.status !== 204) throw new Error(`deleteChat failed: ${res.status}`);
}
