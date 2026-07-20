"use client";

import { useCallback, useRef } from "react";
import { MaterialIcon } from "./MaterialIcon";
import { SuggestionChips } from "./SuggestionChips";

export interface ChatInputProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  disabled?: boolean;
  suggestions?: string[];
}

const DEFAULT_SUGGESTIONS = [
  "Who starred in The Hunger Games?",
  "Sci-fi movies about survival",
  "Highest box-office movies",
  "A movie about a taxi driver and a saxophonist",
];

/** Auto-growing textarea with send button and optional suggestion chips. */
export function ChatInput({
  value,
  onChange,
  onSend,
  disabled = false,
  suggestions = DEFAULT_SUGGESTIONS,
}: ChatInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleInput = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, []);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (value.trim() && !disabled) onSend();
    }
  };

  return (
    <div className="w-full bg-gradient-to-t from-background via-background to-transparent pt-md pb-md px-md z-20 border-t border-hairline flex-shrink-0">
      <div className="w-full">
        <SuggestionChips
          suggestions={suggestions}
          onSelect={(text) => {
            onChange(text);
            textareaRef.current?.focus();
          }}
        />
        <div className="relative flex items-end bg-canvas rounded-xl border border-hairline focus-within:border-primary-container focus-within:shadow-[0_0_8px_rgba(232,180,87,0.2)] transition-all duration-300">
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => {
              onChange(e.target.value);
              handleInput();
            }}
            onKeyDown={handleKeyDown}
            disabled={disabled}
            aria-label="Message Reel"
            className="w-full bg-transparent border-none text-on-surface font-body-lg text-body-lg p-md pr-[60px] resize-none focus:ring-0 min-h-[56px] max-h-[200px] thin-scrollbar"
            placeholder="Ask about cast, genres, plots, or box office..."
            rows={1}
          />
          <button
            type="button"
            onClick={onSend}
            disabled={disabled || !value.trim()}
            aria-label="Send message"
            className="absolute right-sm bottom-sm w-10 h-10 rounded-full bg-primary-container text-on-primary-container flex items-center justify-center hover:brightness-110 transition-all flex-shrink-0 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <MaterialIcon name="arrow_upward" size={20} />
          </button>
        </div>
      </div>
    </div>
  );
}
