import { useState, useRef, useCallback, useEffect } from 'react'
import { Capacitor } from '@capacitor/core'
import TTS from '../plugins/tts'

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

const isNative = Capacitor.isNativePlatform()

// ---------------------------------------------------------------------------
// Native implementation (Capacitor / iOS)
// Uses AVSpeechSynthesizer via native plugin. Proper pause/resume support,
// word-level boundary events, no cancel-and-re-speak hack needed.
// ---------------------------------------------------------------------------

function useNativeTTS(): UseTTSReturn {
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [isPaused, setIsPaused] = useState(false)
  const [progress, setProgress] = useState(0)

  const fullTextRef = useRef('')
  const offsetRef = useRef(0)

  // Set up native plugin listeners
  useEffect(() => {
    const listeners: Array<{ remove: () => void }> = []

    const setup = async () => {
      const startListener = await TTS.addListener('start', () => {
        setIsSpeaking(true)
        setIsPaused(false)
      })
      listeners.push(startListener)

      const endListener = await TTS.addListener('end', () => {
        setIsSpeaking(false)
        setIsPaused(false)
        setProgress(1)
      })
      listeners.push(endListener)

      const pauseListener = await TTS.addListener('pause', () => {
        setIsSpeaking(false)
        setIsPaused(true)
      })
      listeners.push(pauseListener)

      const resumeListener = await TTS.addListener('resume', () => {
        setIsSpeaking(true)
        setIsPaused(false)
      })
      listeners.push(resumeListener)

      const boundaryListener = await TTS.addListener('boundary', (data) => {
        setProgress(data.progress)
        offsetRef.current = data.charIndex
      })
      listeners.push(boundaryListener)
    }

    setup()

    return () => {
      listeners.forEach((l) => l.remove())
      TTS.stop().catch(() => {})
    }
  }, [])

  const speak = useCallback((text: string) => {
    fullTextRef.current = text
    offsetRef.current = 0
    setProgress(0)
    TTS.speak({ text }).catch(() => {})
  }, [])

  const pause = useCallback(() => {
    TTS.pause().catch(() => {})
  }, [])

  const resume = useCallback(() => {
    TTS.resume().catch(() => {})
  }, [])

  const stop = useCallback(() => {
    fullTextRef.current = ''
    offsetRef.current = 0
    setIsSpeaking(false)
    setIsPaused(false)
    setProgress(0)
    TTS.stop().catch(() => {})
  }, [])

  const skipForward = useCallback(() => {
    if (!fullTextRef.current) return
    const newOffset = Math.min(
      offsetRef.current + SKIP_CHARS,
      fullTextRef.current.length
    )
    TTS.speak({
      text: fullTextRef.current,
      offset: newOffset,
    }).catch(() => {})
  }, [])

  const skipBack = useCallback(() => {
    if (!fullTextRef.current) return
    const newOffset = Math.max(offsetRef.current - SKIP_CHARS, 0)
    TTS.speak({
      text: fullTextRef.current,
      offset: newOffset,
    }).catch(() => {})
  }, [])

  return {
    isSpeaking,
    isPaused,
    speak,
    pause,
    resume,
    stop,
    skipForward,
    skipBack,
    isSupported: true,
    progress,
  }
}

// ---------------------------------------------------------------------------
// Web Speech API implementation (desktop browsers only)
// No iOS workarounds needed -- iOS uses native plugin above.
// Desktop browsers support pause/resume properly.
// ---------------------------------------------------------------------------

function useWebTTS(): UseTTSReturn {
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [isPaused, setIsPaused] = useState(false)
  const [progress, setProgress] = useState(0)

  const fullTextRef = useRef('')
  const offsetRef = useRef(0)
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null)
  const voicesRef = useRef<SpeechSynthesisVoice[]>([])

  const isSupported =
    typeof window !== 'undefined' && 'speechSynthesis' in window

  // Load voices
  useEffect(() => {
    if (!isSupported) return

    const loadVoices = () => {
      voicesRef.current = window.speechSynthesis.getVoices()
    }

    loadVoices()
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

      utterance.onboundary = (event: SpeechSynthesisEvent) => {
        if (fullTextRef.current.length > 0) {
          const currentPosition = offset + event.charIndex
          offsetRef.current = currentPosition
          setProgress(
            Math.min(currentPosition / fullTextRef.current.length, 1)
          )
        }
      }

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

  // Desktop browsers support pause/resume natively -- no cancel-and-re-speak hack
  const pause = useCallback(() => {
    if (!isSupported || !window.speechSynthesis.speaking) return
    window.speechSynthesis.pause()
    setIsSpeaking(false)
    setIsPaused(true)
  }, [isSupported])

  const resume = useCallback(() => {
    if (!isSupported || !isPaused) return
    window.speechSynthesis.resume()
    setIsPaused(false)
    setIsSpeaking(true)
  }, [isSupported, isPaused])

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
    const newOffset = Math.min(
      offsetRef.current + SKIP_CHARS,
      fullTextRef.current.length
    )
    speakFromOffset(fullTextRef.current, newOffset)
  }, [speakFromOffset])

  const skipBack = useCallback(() => {
    if (!fullTextRef.current) return
    const newOffset = Math.max(offsetRef.current - SKIP_CHARS, 0)
    speakFromOffset(fullTextRef.current, newOffset)
  }, [speakFromOffset])

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

// ---------------------------------------------------------------------------
// Export: pick implementation at module load time (not at render time).
// This satisfies React's rules of hooks -- the same function is always called.
// ---------------------------------------------------------------------------

export const useTTS: () => UseTTSReturn = isNative ? useNativeTTS : useWebTTS
