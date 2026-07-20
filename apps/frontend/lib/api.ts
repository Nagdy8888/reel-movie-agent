import { z } from "zod";
import { publicEnv } from "./env";

const API = publicEnv.apiUrl;

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
  type: "Movie" | "Person" | "Genre" | "Keyword";
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

const conversationSummarySchema = z.object({
  id: z.string(),
  thread_id: z.string(),
  title: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

const messageOutSchema: z.ZodType<MessageOut> = z.object({
  role: z.enum(["user", "assistant"]),
  content: z.string(),
  created_at: z.string(),
});

const conversationDetailSchema: z.ZodType<ConversationDetail> =
  conversationSummarySchema.extend({
    messages: z.array(messageOutSchema),
  });

const sourceSummarySchema: z.ZodType<SourceSummary> = z.object({
  id: z.string(),
  title: z.string(),
  subtitle: z.string().nullable().optional(),
  year: z.string().nullable().optional(),
  poster_url: z.string().nullable().optional(),
  tags: z.array(z.string()),
});

const graphNodeSchema: z.ZodType<GraphNode> = z.object({
  id: z.string(),
  label: z.string(),
  type: z.enum(["Movie", "Person", "Genre", "Keyword"]),
});

const graphLinkSchema: z.ZodType<GraphLink> = z.object({
  source: z.string(),
  target: z.string(),
  label: z.string(),
});

const graphDataSchema: z.ZodType<GraphData> = z.object({
  nodes: z.array(graphNodeSchema),
  links: z.array(graphLinkSchema),
});

/** Discriminated union of SSE events emitted by POST /chat. */
export type ChatEvent =
  | { type: "meta"; thread_id: string; conversation_id: string }
  | { type: "token"; text: string }
  | { type: "sources"; sources: SourceSummary[] }
  | { type: "graph"; graph: GraphData }
  | { type: "done" };

/** Parse and validate one SSE frame, returning null for malformed or unknown data. */
export function parseSseFrame(frame: string): ChatEvent | null {
  let eventName = "message";
  const dataLines: string[] = [];

  for (const rawLine of frame.replace(/\r/g, "").split("\n")) {
    if (rawLine.startsWith("event:")) {
      eventName = rawLine.slice(6).trim();
    } else if (rawLine.startsWith("data:")) {
      dataLines.push(rawLine.slice(5).trimStart());
    }
  }

  if (dataLines.length === 0) return null;

  let payload: unknown;
  try {
    payload = JSON.parse(dataLines.join("\n"));
  } catch {
    return null;
  }

  if (eventName === "done") return { type: "done" };

  if (eventName === "meta") {
    const parsed = z
      .object({ thread_id: z.string(), conversation_id: z.string() })
      .safeParse(payload);
    return parsed.success ? { type: "meta", ...parsed.data } : null;
  }

  if (eventName === "sources") {
    const parsed = z.object({ sources: z.array(sourceSummarySchema) }).safeParse(payload);
    return parsed.success ? { type: "sources", sources: parsed.data.sources } : null;
  }

  if (eventName === "graph") {
    const parsed = graphDataSchema.safeParse(payload);
    return parsed.success ? { type: "graph", graph: parsed.data } : null;
  }

  const parsed = z.object({ token: z.string() }).safeParse(payload);
  return parsed.success ? { type: "token", text: parsed.data.token } : null;
}

/** Decode and validate one JSON response without trusting the network boundary. */
async function parseJsonResponse<T>(
  response: Response,
  schema: z.ZodType<T>,
  operation: string,
): Promise<T> {
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`${operation} returned invalid JSON`);
  }

  const parsed = schema.safeParse(payload);
  if (!parsed.success) {
    throw new Error(`${operation} returned an invalid response`);
  }
  return parsed.data;
}

/** Stream an answer from POST /chat while skipping isolated malformed SSE frames. */
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
    const frames = buffer.replace(/\r\n/g, "\n").split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const event = parseSseFrame(frame);
      if (event) yield event;
    }
  }

  buffer += decoder.decode();
  const finalEvent = parseSseFrame(buffer);
  if (finalEvent) yield finalEvent;
}

/** List the current user's conversations (newest first). */
export async function listChats(token: string): Promise<ConversationSummary[]> {
  const res = await fetch(`${API}/chats`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (res.status === 401 || res.status === 403) throw new Error("unauthorized");
  if (!res.ok) throw new Error(`listChats failed: ${res.status}`);
  return parseJsonResponse(res, z.array(conversationSummarySchema), "listChats");
}

/** Fetch one conversation with its messages. */
export async function getChat(id: string, token: string): Promise<ConversationDetail> {
  const res = await fetch(`${API}/chats/${id}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (res.status === 401 || res.status === 403) throw new Error("unauthorized");
  if (!res.ok) throw new Error(`getChat failed: ${res.status}`);
  return parseJsonResponse(res, conversationDetailSchema, "getChat");
}

/** Fetch the full movie knowledge graph used by the main canvas. */
export async function getFullGraph(token: string): Promise<GraphData> {
  const res = await fetch(`${API}/graph`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (res.status === 401 || res.status === 403) throw new Error("unauthorized");
  if (!res.ok) throw new Error(`getFullGraph failed: ${res.status}`);
  return parseJsonResponse(res, graphDataSchema, "getFullGraph");
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
