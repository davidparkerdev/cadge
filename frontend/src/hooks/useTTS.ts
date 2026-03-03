import { useState, useRef, useCallback, useEffect } from 'react'

export interface UseTTSReturn {
  isSpeaking: boolean
  isPaused: boolean
  speak: (text: string) => void
  pause: () => void
  resume: () => void
  stop: () => void
  skipForward: () => void
  skipBack: () => void
  isSupported: boolean
  progress: number
}

// Approximate characters spoken per second at normal rate
const CHARS_PER_SECOND = 20
const SKIP_CHARS = CHARS_PER_SECOND * 10 // ~10 seconds of speech

export function useTTS(): UseTTSReturn {
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [isPaused, setIsPaused] = useState(false)
  const [progress, setProgress] = useState(0)

  const fullTextRef = useRef('')
  const offsetRef = useRef(0)
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null)
  const voicesRef = useRef<SpeechSynthesisVoice[]>([])

  const isSupported =
    typeof window !== 'undefined' && 'speechSynthesis' in window

  // Load voices asynchronously -- getVoices() returns [] on first call in many browsers
  useEffect(() => {
    if (!isSupported) return

    const loadVoices = () => {
      voicesRef.current = window.speechSynthesis.getVoices()
    }

    // Try immediately (may already be loaded)
    loadVoices()

    // Listen for async voice loading
    window.speechSynthesis.addEventListener('voiceschanged', loadVoices)
    return () => {
      window.speechSynthesis.removeEventListener('voiceschanged', loadVoices)
    }
  }, [isSupported])

  const pickVoice = useCallback((): SpeechSynthesisVoice | null => {
    const voices = voicesRef.current
    if (voices.length === 0) return null

    const preferred = voices.find(
      (v) =>
        v.lang.startsWith('en') &&
        (v.name.includes('Samantha') ||
          v.name.includes('Google') ||
          v.name.includes('Natural') ||
          v.name.includes('Enhanced'))
    )
    const fallback = voices.find((v) => v.lang.startsWith('en'))
    return preferred || fallback || null
  }, [])

  const speakFromOffset = useCallback(
    (text: string, offset: number) => {
      if (!isSupported) return

      // Cancel any current speech
      window.speechSynthesis.cancel()

      const remainingText = text.slice(offset)
      if (!remainingText.trim()) {
        setIsSpeaking(false)
        setIsPaused(false)
        setProgress(1)
        return
      }

      const utterance = new SpeechSynthesisUtterance(remainingText)
      utterance.rate = 1.0
      utterance.pitch = 1.0

      const voice = pickVoice()
      if (voice) {
        utterance.voice = voice
      }

      utterance.onstart = () => {
        setIsSpeaking(true)
        setIsPaused(false)
      }

      utterance.onend = () => {
        setIsSpeaking(false)
        setIsPaused(false)
        setProgress(1)
      }

      // Track progress via boundary events
      utterance.onboundary = (event: SpeechSynthesisEvent) => {
        if (fullTextRef.current.length > 0) {
          const currentPosition = offset + event.charIndex
          setProgress(
            Math.min(currentPosition / fullTextRef.current.length, 1)
          )
        }
      }

      // NOTE: We do NOT use utterance.onpause/onresume because iOS Safari
      // does not support speechSynthesis.pause()/resume(). Instead we implement
      // pause/resume using cancel + speakFromOffset (see below).

      utteranceRef.current = utterance
      offsetRef.current = offset
      window.speechSynthesis.speak(utterance)
    },
    [isSupported, pickVoice]
  )

  const speak = useCallback(
    (text: string) => {
      fullTextRef.current = text
      offsetRef.current = 0
      setProgress(0)
      speakFromOffset(text, 0)
    },
    [speakFromOffset]
  )

  // iOS-compatible pause: cancel current speech, save position, resume by re-speaking
  // (speechSynthesis.pause()/resume() are no-ops on iOS Safari)
  const pause = useCallback(() => {
    if (!isSupported || !isSpeaking) return

    // Estimate current character position from progress
    const savedOffset = Math.floor(progress * fullTextRef.current.length)
    offsetRef.current = savedOffset

    window.speechSynthesis.cancel()
    setIsSpeaking(false)
    setIsPaused(true)
  }, [isSupported, isSpeaking, progress])

  const resume = useCallback(() => {
    if (!isSupported || !isPaused) return
    setIsPaused(false)
    speakFromOffset(fullTextRef.current, offsetRef.current)
  }, [isSupported, isPaused, speakFromOffset])

  const stop = useCallback(() => {
    if (!isSupported) return
    window.speechSynthesis.cancel()
    fullTextRef.current = ''
    offsetRef.current = 0
    setIsSpeaking(false)
    setIsPaused(false)
    setProgress(0)
  }, [isSupported])

  const skipForward = useCallback(() => {
    if (!fullTextRef.current) return

    const currentPos = Math.floor(progress * fullTextRef.current.length)
    const newOffset = Math.min(
      currentPos + SKIP_CHARS,
      fullTextRef.current.length
    )
    speakFromOffset(fullTextRef.current, newOffset)
  }, [progress, speakFromOffset])

  const skipBack = useCallback(() => {
    if (!fullTextRef.current) return

    const currentPos = Math.floor(progress * fullTextRef.current.length)
    const newOffset = Math.max(currentPos - SKIP_CHARS, 0)
    speakFromOffset(fullTextRef.current, newOffset)
  }, [progress, speakFromOffset])

  // Clean up on unmount
  useEffect(() => {
    return () => {
      if (isSupported) {
        window.speechSynthesis.cancel()
      }
    }
  }, [isSupported])

  return {
    isSpeaking,
    isPaused,
    speak,
    pause,
    resume,
    stop,
    skipForward,
    skipBack,
    isSupported,
    progress,
  }
}
