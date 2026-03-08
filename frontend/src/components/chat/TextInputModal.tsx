import { useState, useEffect, useRef } from 'react'
import { Xmark, SendDiagonal } from 'iconoir-react'
import { cn } from '../../lib/cn'

interface TextInputModalProps {
  isOpen: boolean
  onClose: () => void
  onSend: (text: string) => void
  initialText?: string
}

export function TextInputModal({
  isOpen,
  onClose,
  onSend,
  initialText = '',
}: TextInputModalProps) {
  const [text, setText] = useState(initialText)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Reset text and auto-focus when modal opens
  // NOTE: setTimeout(0) is used instead of requestAnimationFrame because
  // iOS Safari requires focus() to be in a user-gesture-adjacent context
  // to raise the software keyboard. rAF breaks that requirement.
  useEffect(() => {
    if (isOpen) {
      setText(initialText)
      setTimeout(() => {
        textareaRef.current?.focus()
      }, 0)
    }
  }, [isOpen, initialText])

  const handleSend = () => {
    const trimmed = text.trim()
    if (!trimmed) return
    onSend(trimmed)
    setText('')
    onClose()
  }

  const handleCancel = () => {
    setText('')
    onClose()
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-surface-primary/95 backdrop-blur-sm safe-area-top">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <button
          type="button"
          onClick={handleCancel}
          className="p-2 -m-2 rounded-lg text-text-secondary active:bg-surface-tertiary transition-colors touch-manipulation"
          aria-label="Cancel"
        >
          <Xmark className="w-5 h-5" />
        </button>

        <span className="text-sm font-medium text-text-primary">
          Type Message
        </span>

        <button
          type="button"
          onClick={handleSend}
          disabled={!text.trim()}
          className={cn(
            'p-2 -m-2 rounded-lg transition-colors touch-manipulation',
            text.trim()
              ? 'text-accent active:bg-accent/20'
              : 'text-text-secondary opacity-40'
          )}
          aria-label="Send"
        >
          <SendDiagonal className="w-5 h-5" />
        </button>
      </div>

      {/* Textarea */}
      <div className="flex-1 p-4">
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Type your message..."
          className={cn(
            'w-full h-full resize-none rounded-lg px-4 py-3 text-base',
            'bg-surface-secondary border border-border text-text-primary',
            'placeholder:text-text-secondary',
            'focus:outline-none focus:border-accent/50 focus:ring-1 focus:ring-accent/30',
            'touch-manipulation'
          )}
        />
      </div>
    </div>
  )
}
