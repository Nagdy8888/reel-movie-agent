/** Citation chip shown beneath assistant messages when sources exist. */
export interface CitationChipProps {
  /** Display index (e.g. 1 for ①). */
  index: number;
  /** Citation label text. */
  label: string;
}

const CIRCLED_NUMBERS = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩"];

/** Render a numbered citation chip. */
export function CitationChip({ index, label }: CitationChipProps) {
  const symbol = CIRCLED_NUMBERS[index - 1] ?? String(index);
  return (
    <button
      type="button"
      className="px-sm py-1 rounded-full bg-surface-container/50 border border-hairline text-primary-container font-label-caps text-[11px] flex items-center gap-1 hover:bg-surface-variant transition-colors"
    >
      <span>{symbol}</span>
      <span>{label}</span>
    </button>
  );
}
