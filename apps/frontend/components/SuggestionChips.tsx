export interface SuggestionChipsProps {
  suggestions: string[];
  onSelect: (text: string) => void;
}

/** Static prompt-starter chips above the chat input. */
export function SuggestionChips({ suggestions, onSelect }: SuggestionChipsProps) {
  return (
    <div className="flex gap-sm mb-md overflow-x-auto thin-scrollbar pb-1">
      {suggestions.map((text) => (
        <button
          key={text}
          type="button"
          onClick={() => onSelect(text)}
          className="whitespace-nowrap px-md py-sm rounded-full border border-hairline bg-elevated/80 text-on-surface-variant font-body-sm text-body-sm hover:border-primary-container hover:text-primary-container transition-colors backdrop-blur-md"
        >
          {text}
        </button>
      ))}
    </div>
  );
}
