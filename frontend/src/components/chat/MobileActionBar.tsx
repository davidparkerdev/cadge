import { useState, useMemo, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  NavArrowLeft,
  NavArrowRight,
  Microphone,
  Play,
  MediaImage,
  InputField,
  ArrowDown,
  SendDiagonal,
  Xmark,
  Flash,
  RefreshDouble,
  Check,
  Hammer,
  Terminal,
  FastArrowRight,
  GitCommit,
  Minus,
  Erase,
} from 'iconoir-react'
import { cn } from '../../lib/cn'
import { useSessionsContext } from '../../contexts/SessionsContext'
import { useVoiceInput } from '../../hooks/useVoiceInput'
import { useTTS } from '../../hooks/useTTS'
import { useImageAttachment } from '../../hooks/useImageAttachment'
import { TextInputModal } from './TextInputModal'
import { PlaybackBar } from './PlaybackBar'
import { ImagePreviewBar } from './ImagePreviewBar'

interface MobileActionBarProps {
  onSend: (content: string, images?: string[]) => void
  onScrollToBottom: () => void
  disabled?: boolean
  lastAssistantMessage?: string
}

export function MobileActionBar({
  onSend,
  onScrollToBottom,
  disabled = false,
  lastAssistantMessage,
}: MobileActionBarProps) {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { sessions } = useSessionsContext()

  const [typedText, setTypedText] = useState('')
  const [isTextModalOpen, setIsTextModalOpen] = useState(false)
  const [isCommandsOpen, setIsCommandsOpen] = useState(false)
  const [isCollapsed, setIsCollapsed] = useState(false)

  // Order matters: grid fills left-to-right in 4 cols.
  // Row 1: [empty] [empty] Hide Cmds   (pinned, not in this array)
  // Row 2: Commit  Do      Status OAR!
  // Row 3: Clear   Done    Fix    Continue
  const cmdAction = 'bg-green-500/20 text-green-400'
  const cmdUtil = 'bg-gray-500/20 text-gray-300'
  const quickCommands = [
    { label: 'Commit', message: 'CBGS', icon: GitCommit, color: cmdAction },
    { label: 'Do', message: 'Do ', icon: Hammer, color: cmdAction, prefill: true },
    { label: 'Status', message: 'Status concise', icon: Terminal, color: cmdUtil },
    { label: 'OAR!', message: 'OAR!', icon: Flash, color: 'bg-amber-500/20 text-amber-400' },
    { label: 'Clear', message: '', icon: Erase, color: 'bg-red-500/20 text-red-400', action: 'clear' as const },
    { label: 'Done', message: 'Mark as Done', icon: Check, color: cmdAction },
    { label: 'Fix', message: 'then fix it', icon: RefreshDouble, color: cmdAction },
    { label: 'Continue', message: 'Continue from where you left off.', icon: FastArrowRight, color: cmdUtil },
  ]

  const handleQuickCommand = (cmd: typeof quickCommands[number]) => {
    setIsCommandsOpen(false)
    if ('action' in cmd && cmd.action === 'clear') {
      navigate('/')
    } else if (cmd.prefill) {
      // Open text modal pre-filled so user can append (e.g. ticket ID)
      setTypedText(cmd.message)
      setIsTextModalOpen(true)
    } else {
      onSend(cmd.message)
    }
  }

  // Voice input (speech-to-text)
  const voice = useVoiceInput()

  // Text-to-speech playback
  const tts = useTTS()

  // Image attachment
  const imageAttachment = useImageAttachment()

  // Find current session index for prev/next navigation
  const currentIndex = useMemo(() => {
    if (!id) return -1
    return sessions.findIndex((s) => s.id === id)
  }, [sessions, id])

  const hasPrevious = currentIndex > 0
  const hasNext = currentIndex >= 0 && currentIndex < sessions.length - 1

  const handlePrevious = () => {
    if (hasPrevious) {
      navigate(`/session/${sessions[currentIndex - 1].id}`)
    }
  }

  const handleNext = () => {
    if (hasNext) {
      navigate(`/session/${sessions[currentIndex + 1].id}`)
    }
  }

  // The display text: live transcript when recording, otherwise typed text
  const displayText = voice.isRecording
    ? voice.transcript + (voice.interimTranscript ? ` ${voice.interimTranscript}` : '')
    : typedText

  const hasText = displayText.trim().length > 0

  const handleTextModalSend = (text: string) => {
    setIsTextModalOpen(false)
    // Send directly -- don't just stage in preview, the user expects Send to send
    if (!disabled && text.trim()) {
      onSend(text.trim())
    }
  }

  const handleTalkToggle = useCallback(() => {
    if (voice.isRecording) {
      // Cancel recording
      voice.cancelRecording()
    } else {
      // Start recording
      voice.startRecording()
    }
  }, [voice])

  const handlePlayToggle = useCallback(() => {
    if (tts.isSpeaking || tts.isPaused) {
      tts.stop()
    } else if (lastAssistantMessage) {
      tts.speak(lastAssistantMessage)
    }
  }, [tts, lastAssistantMessage])

  const handleSend = useCallback(() => {
    if (disabled) return

    let content = ''

    if (voice.isRecording) {
      // Use the visible displayText (includes both final + interim transcript)
      // instead of stopRecording()'s return value, because on iOS the final
      // onresult event fires AFTER stop() returns, making the ref empty.
      content = (voice.transcript + ' ' + voice.interimTranscript).trim()
      voice.stopRecording()
    } else {
      content = typedText.trim()
    }

    if (!content) return

    // Collect base64 images from staged attachments
    const images = imageAttachment.images
      .map((img) => img.base64)
      .filter((b): b is string => !!b)

    onSend(content, images.length > 0 ? images : undefined)
    setTypedText('')
    imageAttachment.clearImages()
  }, [disabled, voice, typedText, onSend, imageAttachment])

  const btnBase =
    'h-20 rounded-xl flex flex-col items-center justify-center gap-1 text-xs font-medium touch-manipulation active:scale-95 transition-transform'

  return (
    <>
      <TextInputModal
        isOpen={isTextModalOpen}
        onClose={() => setIsTextModalOpen(false)}
        onSend={handleTextModalSend}
        initialText={typedText}
      />

      {/* Hidden file input for image picker */}
      <input
        ref={imageAttachment.inputRef}
        type="file"
        accept="image/*"
        multiple
        hidden
        onChange={(e) =>
          e.target.files && imageAttachment.addImages(e.target.files)
        }
      />

      <div className="border-t border-border bg-surface-secondary pb-[env(safe-area-inset-bottom)]">
        {isCollapsed ? (
          /* ---- COLLAPSED: just one expand button, right-aligned ---- */
          <div className="flex justify-end p-3">
            <button
              type="button"
              onClick={() => setIsCollapsed(false)}
              className={cn(
                btnBase,
                'relative',
                voice.isRecording
                  ? 'bg-red-500/20 text-red-400'
                  : 'bg-gray-500/20 text-gray-400'
              )}
              style={{ width: 'calc(25% - 6px)' }}
              aria-label="Expand action bar"
            >
              {voice.isRecording && (
                <span className="absolute top-2 right-2 w-3 h-3 rounded-full bg-red-500 animate-pulse" />
              )}
              <Minus className="w-6 h-6 rotate-90" />
              <span>{voice.isRecording ? 'Rec...' : 'Show'}</span>
            </button>
          </div>
        ) : (
          /* ---- EXPANDED: full bar ---- */
          <>
            {/* TTS Playback bar */}
            <PlaybackBar
              isSpeaking={tts.isSpeaking}
              isPaused={tts.isPaused}
              progress={tts.progress}
              onPause={tts.pause}
              onResume={tts.resume}
              onStop={tts.stop}
              onSkipBack={tts.skipBack}
              onSkipForward={tts.skipForward}
            />

            {/* Image preview bar */}
            <ImagePreviewBar
              images={imageAttachment.images}
              onRemove={imageAttachment.removeImage}
            />

            {/* Voice/text preview */}
            {(hasText || voice.isRecording) && (
              <div className="px-3 pt-2 flex items-start gap-2">
                {voice.isRecording && (
                  <span className="w-2 h-2 mt-2.5 rounded-full bg-red-500 animate-pulse flex-shrink-0" />
                )}
                <p className="flex-1 text-sm text-text-secondary bg-surface-tertiary rounded-lg px-3 py-2 max-h-28 overflow-y-auto whitespace-pre-wrap break-words leading-relaxed">
                  {displayText || (voice.isRecording ? 'Listening...' : '')}
                </p>
                {!voice.isRecording && hasText && (
                  <button
                    type="button"
                    onClick={() => setTypedText('')}
                    className="p-1 mt-1 text-text-secondary active:text-text-primary touch-manipulation flex-shrink-0"
                    aria-label="Clear text"
                  >
                    <Xmark className="w-4 h-4" />
                  </button>
                )}
              </div>
            )}

            {/* Image attachment error */}
            {imageAttachment.error && (
              <div className="px-3 pt-1">
                <p className="text-xs text-red-400">{imageAttachment.error}</p>
              </div>
            )}

            {/* Voice error */}
            {voice.error && (
              <div className="px-3 pt-1">
                <p className="text-xs text-red-400">Voice: {voice.error}</p>
              </div>
            )}

            {/* Unified action grid */}
            <div className="grid grid-cols-4 gap-2 p-3">

              {/* Row 1: Hide + Cmds -- ALWAYS first, pinned to cols 3-4 */}
              <button
                type="button"
                onClick={() => setIsCollapsed(true)}
                className={cn(btnBase, 'bg-gray-500/20 text-gray-400 col-start-3')}
                aria-label="Collapse action bar"
              >
                <Minus className="w-6 h-6" />
                <span>Hide</span>
              </button>

              <button
                type="button"
                onClick={() => setIsCommandsOpen(!isCommandsOpen)}
                className={cn(
                  btnBase,
                  isCommandsOpen
                    ? 'bg-amber-500/30 text-amber-300'
                    : 'bg-amber-500/20 text-amber-400',
                )}
                aria-label={isCommandsOpen ? 'Close commands' : 'Quick commands'}
              >
                <Flash className="w-6 h-6" />
                <span>Cmds</span>
              </button>

              {/* Below: either quick commands or regular action buttons */}
              {isCommandsOpen ? (
                <>
                  {quickCommands.map((cmd) => (
                    <button
                      key={cmd.label}
                      type="button"
                      onClick={() => handleQuickCommand(cmd)}
                      className={cn(btnBase, cmd.color)}
                      aria-label={cmd.label}
                    >
                      <cmd.icon className="w-6 h-6" />
                      <span>{cmd.label}</span>
                    </button>
                  ))}
                </>
              ) : (
                <>
                  {/* Row: Previous, Talk, Play, Next */}
                  <button
                    type="button"
                    onClick={handlePrevious}
                    disabled={!hasPrevious}
                    className={cn(
                      btnBase,
                      'bg-gray-500/20 text-gray-400',
                      !hasPrevious && 'opacity-30'
                    )}
                    aria-label="Previous session"
                  >
                    <NavArrowLeft className="w-6 h-6" />
                    <span>Previous</span>
                  </button>

                  <button
                    type="button"
                    onClick={handleTalkToggle}
                    disabled={!voice.isSupported}
                    className={cn(
                      btnBase,
                      voice.isRecording
                        ? 'bg-red-500/20 text-red-400'
                        : 'bg-green-500/20 text-green-400',
                      !voice.isSupported && 'opacity-30'
                    )}
                    aria-label={voice.isRecording ? 'Cancel recording' : 'Start recording'}
                  >
                    {voice.isRecording ? (
                      <Xmark className="w-6 h-6" />
                    ) : (
                      <Microphone className="w-6 h-6" />
                    )}
                    <span>{voice.isRecording ? 'Cancel' : 'Talk'}</span>
                  </button>

                  <button
                    type="button"
                    onClick={handlePlayToggle}
                    disabled={!tts.isSupported || (!lastAssistantMessage && !tts.isSpeaking)}
                    className={cn(
                      btnBase,
                      tts.isSpeaking || tts.isPaused
                        ? 'bg-red-500/20 text-red-400'
                        : 'bg-green-500/20 text-green-400',
                      !tts.isSupported && 'opacity-30',
                      !lastAssistantMessage && !tts.isSpeaking && 'opacity-30'
                    )}
                    aria-label={tts.isSpeaking ? 'Stop playback' : 'Play response'}
                  >
                    {tts.isSpeaking || tts.isPaused ? (
                      <Xmark className="w-6 h-6" />
                    ) : (
                      <Play className="w-6 h-6" />
                    )}
                    <span>{tts.isSpeaking || tts.isPaused ? 'Stop' : 'Play'}</span>
                  </button>

                  <button
                    type="button"
                    onClick={handleNext}
                    disabled={!hasNext}
                    className={cn(
                      btnBase,
                      'bg-gray-500/20 text-gray-400',
                      !hasNext && 'opacity-30'
                    )}
                    aria-label="Next session"
                  >
                    <NavArrowRight className="w-6 h-6" />
                    <span>Next</span>
                  </button>

                  {/* Row: Image, Type, Bottom, Send */}
                  <button
                    type="button"
                    onClick={imageAttachment.openPicker}
                    className={cn(btnBase, 'bg-gray-500/20 text-gray-300')}
                    aria-label="Attach image"
                  >
                    <MediaImage className="w-6 h-6" />
                    <span>Image</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => setIsTextModalOpen(true)}
                    className={cn(btnBase, 'bg-gray-500/20 text-gray-300')}
                    aria-label="Type message"
                  >
                    <InputField className="w-6 h-6" />
                    <span>Type</span>
                  </button>

                  <button
                    type="button"
                    onClick={onScrollToBottom}
                    className={cn(btnBase, 'bg-gray-500/20 text-gray-300')}
                    aria-label="Scroll to bottom"
                  >
                    <ArrowDown className="w-6 h-6" />
                    <span>Bottom</span>
                  </button>

                  <button
                    type="button"
                    onClick={handleSend}
                    disabled={disabled || (!hasText && !voice.isRecording)}
                    className={cn(
                      btnBase,
                      hasText || voice.isRecording
                        ? 'bg-green-500/20 text-green-400'
                        : 'bg-gray-500/20 text-gray-500 opacity-30'
                    )}
                    aria-label="Send message"
                  >
                    <SendDiagonal className="w-6 h-6" />
                    <span>Send</span>
                  </button>
                </>
              )}
            </div>
          </>
        )}
      </div>
    </>
  )
}
