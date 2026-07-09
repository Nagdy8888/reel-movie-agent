import type { Source } from "./SourceCard";
import { SourceCard } from "./SourceCard";

export interface SourcesPanelProps {
  sources: Source[];
}

/** Right-pane Sources tab — renders cards or an honest empty state. */
export function SourcesPanel({ sources }: SourcesPanelProps) {
  if (sources.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center p-md text-center">
        <p className="font-body-sm text-body-sm text-on-surface-variant max-w-[240px]">
          Sources will appear here as Reel cites them.
        </p>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto thin-scrollbar p-md space-y-md">
      {sources.map((source) => (
        <SourceCard key={source.id} source={source} />
      ))}
    </div>
  );
}
