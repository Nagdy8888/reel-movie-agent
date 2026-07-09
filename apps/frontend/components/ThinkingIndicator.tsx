import { MaterialIcon } from "./MaterialIcon";

/** Animated thinking indicator shown while awaiting the first streamed token. */
export function ThinkingIndicator() {
  return (
    <div className="flex justify-start w-full gap-md opacity-70">
      <div className="w-8 h-8 rounded-full bg-surface-variant flex items-center justify-center flex-shrink-0 border border-hairline text-on-surface-variant">
        <MaterialIcon name="movie_filter" size={18} />
      </div>
      <div className="bg-elevated px-md py-sm rounded-xl rounded-tl-sm border border-hairline flex items-center gap-md">
        <span className="font-body-sm text-body-sm text-on-surface-variant italic">
          Reel is searching the graph...
        </span>
        <div className="flex gap-1 text-primary-container">
          <span className="thinking-dot text-[24px] leading-none">•</span>
          <span className="thinking-dot text-[24px] leading-none">•</span>
          <span className="thinking-dot text-[24px] leading-none">•</span>
        </div>
      </div>
    </div>
  );
}
