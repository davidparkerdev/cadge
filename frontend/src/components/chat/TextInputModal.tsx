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
  const [keyboardOffset, setKeyboardOffset] = useState(0)

  // Track the visual viewport so we can position above the iOS keyboard.
  // On iOS PWAs, `position: fixed; bottom: 0` stays at the layout viewport
  // bottom, which is BEHIND the keyboard. We use visualViewport to calculate
  // the keyboard height and offset the input bar above it.
  useEffect(() => {
    if (!isOpen) {
      setKeyboardOffset(0)
      return
    }

    const vv = window.visualViewport
    if (!vv) return

    const handleResize = () => {
      // visualViewport.height shrinks when the keyboard opens.
      // The difference = keyboard height.
      const kb = window.innerHeight - vv.height
      setKeyboardOffset(Math.max(0, kb))
    }

    vv.addEventListener('resize', handleResize)
    vv.addEventListener('scroll', handleResize)
    handleResize()

    return () => {
      vv.removeEventListener('resize', handleResize)
      vv.removeEventListener('scroll', handleResize)
    }
  }, [isOpen])

  // Reset text and auto-focus when modal opens.
  // Two-step focus: immediate attempt (preserves user-gesture chain on iOS
  // to raise the keyboard), then a delayed retry in case the DOM wasn't
  // ready on the first try.
  useEffect(() => {
    if (isOpen) {
      setText(initialText)
      textareaRef.current?.focus()
      setTimeout(() => {
        textareaRef.current?.focus()
      }, 50)
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
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-50 bg-black/40"
        onClick={handleCancel}
      />

      {/* Bottom-anchored input — offset above keyboard on iOS */}
      <div
        className="fixed left-0 right-0 z-50 bg-surface-primary border-t border-border"
        style={{
          bottom: keyboardOffset > 0 ? `${keyboardOffset}px` : undefined,
          paddingBottom: keyboardOffset > 0 ? undefined : 'env(safe-area-inset-bottom)',
        }}
      >
        <div className="flex items-end gap-2 px-3 py-3">
          <button
            type="button"
            onClick={handleCancel}
            className="p-2 rounded-lg text-text-secondary active:bg-surface-tertiary transition-colors touch-manipulation flex-shrink-0"
            aria-label="Cancel"
          >
            <Xmark className="w-5 h-5" />
          </button>

          <textarea
            ref={textareaRef}
            value={text}
            onChange={(e) => {
              setText(e.target.value)
              // Auto-resize
              const el = e.target
              el.style.height = 'auto'
              el.style.height = Math.min(el.scrollHeight, 160) + 'px'
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                handleSend()
              }
            }}
            placeholder="Type your message..."
            rows={1}
            className={cn(
              'flex-1 resize-none rounded-lg px-4 py-2.5 text-base',
              'bg-surface-secondary border border-border text-text-primary',
              'placeholder:text-text-secondary',
              'focus:outline-none focus:border-accent/50 focus:ring-1 focus:ring-accent/30',
              'touch-manipulation'
            )}
          />

          <button
            type="button"
            onClick={handleSend}
            disabled={!text.trim()}
            className={cn(
              'p-2 rounded-lg transition-colors touch-manipulation flex-shrink-0',
              text.trim()
                ? 'text-accent active:bg-accent/20'
                : 'text-text-secondary opacity-40'
            )}
            aria-label="Send"
          >
            <SendDiagonal className="w-5 h-5" />
          </button>
        </div>
      </div>
    </>
  )
}
