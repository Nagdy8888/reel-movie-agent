/** Citation chip shown beneath assistant messages when sources exist. */
export interface CitationChipProps {
  /** Stable graph node ID for the cited source. */
  id: string;
  /** Display index (e.g. 1 for ①). */
  index: number;
  /** Citation label text. */
  label: string;
  /** Whether this citation is selected in the graph. */
  selected: boolean;
  /** Focus this citation in the graph. */
  onSelect: (id: string) => void;
}

const CIRCLED_NUMBERS = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩"];

/** Render a numbered citation chip. */
export function CitationChip({ id, index, label, selected, onSelect }: CitationChipProps) {
  const symbol = CIRCLED_NUMBERS[index - 1] ?? String(index);
  return (
    <button
      type="button"
      onClick={() => onSelect(id)}
      aria-pressed={selected}
      aria-label={`Show ${label} in the answer network`}
      className={`px-sm py-1 rounded-full border text-primary-container font-label-caps text-[11px] flex items-center gap-1 transition-colors ${
        selected
          ? "border-primary-container bg-primary-container/20"
          : "border-hairline bg-surface-container/50 hover:bg-surface-variant"
      }`}
    >
      <span>{symbol}</span>
      <span>{label}</span>
    </button>
  );
}
