import { useState, useMemo, useCallback, useEffect, useRef } from 'react'
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
  Activity,
  Tools,
  Square,
} from 'iconoir-react'
import type { Message, AgentInfo } from '../../api/types'
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
  isStreaming?: boolean
  isCancelling?: boolean
  onCancel?: () => void
  streamingMessage?: Message | null
  agents?: AgentInfo[]
  messages?: Message[]
  showTools?: boolean
  onToggleTools?: () => void
}

export function MobileActionBar({
  onSend,
  onScrollToBottom,
  disabled = false,
  lastAssistantMessage,
  isStreaming = false,
  isCancelling = false,
  onCancel,
  streamingMessage,
  agents = [],
  messages = [],
  showTools = false,
  onToggleTools,
}: MobileActionBarProps) {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { sessions } = useSessionsContext()

  const [typedText, setTypedText] = useState('')
  const [isTextModalOpen, setIsTextModalOpen] = useState(false)
  const [isCommandsOpen, setIsCommandsOpen] = useState(false)
  const [isCollapsed, setIsCollapsed] = useState(false)
  const [showStream, setShowStream] = useState(false)

  // Collect ALL tool calls from message history + current stream for the Tools panel
  const allToolCalls = useMemo(() => {
    const calls: { name: string; status: string; messageIndex: number }[] = []
    messages.forEach((msg, idx) => {
      if (msg.role === 'assistant' && Array.isArray(msg.tool_calls)) {
        msg.tool_calls
          .filter((tc) => tc.name !== 'Task')
          .forEach((tc) => {
            calls.push({ name: tc.name, status: tc.status || 'completed', messageIndex: idx })
          })
      }
    })
    // Add currently streaming tool calls
    if (streamingMessage?.tool_calls) {
      streamingMessage.tool_calls
        .filter((tc) => tc.name !== 'Task')
        .forEach((tc) => {
          calls.push({ name: tc.name, status: tc.status || 'running', messageIndex: -1 })
        })
    }
    return calls
  }, [messages, streamingMessage?.tool_calls])

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

  // When voice recording stops involuntarily (iOS auto-stop after max restarts,
  // error, etc.), preserve the transcript as typed text so it's not lost.
  // Without this, displayText switches to empty typedText and the user's
  // spoken words vanish from the screen and can't be sent.
  const prevRecordingRef = useRef(false)
  useEffect(() => {
    if (prevRecordingRef.current && !voice.isRecording && voice.transcript.trim()) {
      setTypedText(voice.transcript.trim())
    }
    prevRecordingRef.current = voice.isRecording
  }, [voice.isRecording, voice.transcript])

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
      // Cancel recording -- user intentionally dismissed, don't preserve transcript.
      // Set prevRecordingRef to false so the useEffect doesn't copy transcript to typedText.
      prevRecordingRef.current = false
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
      // Capture the transcript FIRST from React state (includes both final + interim).
      // This must happen BEFORE stopRecording(), which calls abort() and clears state.
      content = (voice.transcript + ' ' + voice.interimTranscript).trim()
      // Now stop recording -- this uses abort() to immediately release the mic.
      // stopRecording() sets isRecording=false, which triggers the useEffect that
      // normally preserves transcript to typedText. We disable that by setting
      // prevRecordingRef to false FIRST, so the effect sees false->false (no transition).
      prevRecordingRef.current = false
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

      {!isTextModalOpen && <div className="border-t border-border bg-surface-secondary pb-[env(safe-area-inset-bottom)]">
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

            {/* Stream detail panel */}
            {showStream && (
              <div className="mx-3 mt-2 bg-surface-tertiary rounded-lg border border-border max-h-40 overflow-y-auto">
                <div className="px-3 py-2">
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="text-xs font-semibold text-teal-400 uppercase tracking-wide">Stream</span>
                    {isStreaming && <span className="w-1.5 h-1.5 rounded-full bg-teal-400 animate-pulse" />}
                  </div>
                  {streamingMessage?.thinking && (
                    <div className="mb-2">
                      <span className="text-xs font-medium text-amber-400">Thinking:</span>
                      <p className="text-xs text-text-secondary mt-0.5 whitespace-pre-wrap break-words leading-relaxed">
                        {streamingMessage.thinking.slice(-500)}
                      </p>
                    </div>
                  )}
                  {streamingMessage?.content ? (
                    <p className="text-xs text-text-secondary whitespace-pre-wrap break-words leading-relaxed">
                      {streamingMessage.content.slice(-500)}
                    </p>
                  ) : isStreaming ? (
                    <p className="text-xs text-text-secondary">Waiting for response...</p>
                  ) : (
                    <p className="text-xs text-text-secondary">No active stream</p>
                  )}
                </div>
              </div>
            )}

            {/* Unified action grid */}
            <div className="grid grid-cols-4 gap-2 p-3">

              {/* Row 1: Stream, Tools, Hide, Cmds */}
              <button
                type="button"
                onClick={() => { setShowStream(!showStream) }}
                className={cn(
                  btnBase,
                  showStream
                    ? 'bg-teal-500/30 text-teal-300 ring-1 ring-teal-500/40'
                    : 'bg-teal-500/15 text-teal-400',
                  !isStreaming && !streamingMessage?.content && 'opacity-40'
                )}
                aria-label={showStream ? 'Hide stream' : 'Show stream'}
              >
                <Activity className="w-6 h-6" />
                <span>Stream</span>
              </button>

              <button
                type="button"
                onClick={() => { onToggleTools?.(); if (!showTools) setShowStream(false) }}
                className={cn(
                  btnBase,
                  showTools
                    ? 'bg-purple-500/30 text-purple-300 ring-1 ring-purple-500/40'
                    : 'bg-purple-500/15 text-purple-400',
                  allToolCalls.length === 0 && agents.length === 0 && 'opacity-40'
                )}
                aria-label={showTools ? 'Hide tools' : 'Show tools'}
              >
                <Tools className="w-6 h-6" />
                <span>Tools{allToolCalls.length > 0 ? ` (${allToolCalls.length})` : ''}</span>
              </button>

              <button
                type="button"
                onClick={() => setIsCollapsed(true)}
                className={cn(btnBase, 'bg-gray-500/20 text-gray-400')}
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

                  {isStreaming ? (
                    <button
                      type="button"
                      onClick={onCancel}
                      disabled={isCancelling}
                      className={cn(
                        btnBase,
                        isCancelling
                          ? 'bg-amber-500/20 text-amber-400'
                          : 'bg-red-500/20 text-red-400',
                        isCancelling && 'opacity-70'
                      )}
                      aria-label={isCancelling ? 'Cancelling' : 'Stop response'}
                    >
                      <Square className="w-6 h-6" />
                      <span>{isCancelling ? 'Stopping' : 'Stop'}</span>
                    </button>
                  ) : (
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
                  )}
                </>
              )}
            </div>
          </>
        )}
      </div>}
    </>
  )
}
