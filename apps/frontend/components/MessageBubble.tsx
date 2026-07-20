import type { Citation } from "@/lib/chatTypes";
import { MaterialIcon } from "./MaterialIcon";
import { CitationChip } from "./CitationChip";

export interface MessageBubbleProps {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  selectedCitationId?: string | null;
  onCitationSelect?: (id: string) => void;
}

/** Single chat message bubble (user or assistant). */
export function MessageBubble({
  role,
  content,
  citations = [],
  selectedCitationId = null,
  onCitationSelect = () => undefined,
}: MessageBubbleProps) {
  if (role === "user") {
    return (
      <div className="flex justify-end w-full">
        <div className="max-w-[80%] bg-elevated p-md rounded-xl rounded-tr-sm border border-hairline relative overflow-hidden">
          <div className="absolute inset-0 bg-primary-container opacity-5 mix-blend-overlay" />
          <p className="font-body-lg text-body-lg relative z-10 whitespace-pre-wrap">{content}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start w-full gap-md">
      <div className="w-8 h-8 rounded-full bg-surface-variant flex items-center justify-center flex-shrink-0 border border-primary-container/30 text-primary-container">
        <MaterialIcon name="movie_filter" size={18} />
      </div>
      <div className="max-w-[85%]">
        <div className="bg-elevated p-lg rounded-xl rounded-tl-sm border border-hairline shadow-[0_8px_32px_rgba(0,0,0,0.4)]">
          <div className="font-body-lg text-body-lg text-on-surface leading-relaxed whitespace-pre-wrap">
            {content}
          </div>
          {citations.length > 0 && (
            <div className="flex flex-wrap gap-sm mt-lg pt-md border-t border-hairline">
              {citations.map((c) => (
                <CitationChip
                  key={`${c.id}-${c.index}`}
                  id={c.id}
                  index={c.index}
                  label={c.label}
                  selected={selectedCitationId === c.id}
                  onSelect={onCitationSelect}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
