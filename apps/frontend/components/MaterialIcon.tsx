/** Props for the Material Symbols Outlined icon wrapper. */
export interface MaterialIconProps {
  /** Material Symbols icon name (e.g. ``movie_filter``). */
  name: string;
  /** Additional CSS classes. */
  className?: string;
  /** Whether the icon renders filled (FILL 1). */
  filled?: boolean;
  /** Inline font size in pixels. */
  size?: number;
}

/** Render a Material Symbols Outlined icon. */
export function MaterialIcon({ name, className = "", filled = false, size }: MaterialIconProps) {
  return (
    <span
      className={`material-symbols-outlined ${className}`}
      style={{
        fontVariationSettings: `'FILL' ${filled ? 1 : 0}`,
        ...(size !== undefined ? { fontSize: size } : {}),
      }}
    >
      {name}
    </span>
  );
}
