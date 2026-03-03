import { useState, useRef, useCallback, type KeyboardEvent } from 'react'
import { SendDiagonal } from 'iconoir-react'
import { cn } from '../../lib/cn'

interface ChatInputProps {
  onSend: (content: string) => void
  disabled?: boolean
}

export function ChatInput({ onSend, disabled = false }: ChatInputProps) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const handleSend = useCallback(() => {
    const trimmed = value.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setValue('')
    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }, [value, disabled, onSend])

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleInput = () => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    // Clamp between 1 and 5 lines (approx 20px per line + padding)
    const maxHeight = 5 * 24 + 16
    el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`
  }

  return (
    <div className="border-t border-border bg-surface-secondary p-3 md:p-4 pb-[calc(0.75rem+env(safe-area-inset-bottom))] md:pb-4">
      <div className="flex items-end gap-2 max-w-4xl mx-auto">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => {
            setValue(e.target.value)
            handleInput()
          }}
          onKeyDown={handleKeyDown}
          placeholder="Send a message..."
          disabled={disabled}
          rows={1}
          className={cn(
            'flex-1 resize-none rounded-lg px-4 py-3 text-base md:text-sm',
            'bg-surface-primary border border-border text-text-primary',
            'placeholder:text-text-secondary',
            'focus:outline-none focus:border-accent/50 focus:ring-1 focus:ring-accent/30',
            'disabled:opacity-50 disabled:cursor-not-allowed',
            'transition-colors touch-manipulation'
          )}
        />
        <button
          type="button"
          onClick={handleSend}
          disabled={disabled || !value.trim()}
          className={cn(
            'flex items-center justify-center w-11 h-11 rounded-lg',
            'bg-accent text-surface-primary',
            'hover:bg-accent/90 active:bg-accent/80 transition-colors',
            'disabled:opacity-40 disabled:cursor-not-allowed',
            'flex-shrink-0 touch-manipulation'
          )}
          aria-label="Send message"
        >
          <SendDiagonal className="w-5 h-5" />
        </button>
      </div>
    </div>
  )
}
