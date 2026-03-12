import { useState, useRef, useCallback, useEffect } from 'react'

// Web Speech API types
interface SpeechRecognitionEvent extends Event {
  results: SpeechRecognitionResultList
  resultIndex: number
}

interface SpeechRecognitionResultList {
  length: number
  item(index: number): SpeechRecognitionResult
  [index: number]: SpeechRecognitionResult
}

interface SpeechRecognitionResult {
  length: number
  item(index: number): SpeechRecognitionAlternative
  [index: number]: SpeechRecognitionAlternative
  isFinal: boolean
}

interface SpeechRecognitionAlternative {
  transcript: string
  confidence: number
}

interface SpeechRecognitionInstance extends EventTarget {
  continuous: boolean
  interimResults: boolean
  lang: string
  start(): void
  stop(): void
  abort(): void
  onresult: ((event: SpeechRecognitionEvent) => void) | null
  onerror: ((event: Event & { error: string }) => void) | null
  onend: (() => void) | null
  onstart: (() => void) | null
}

declare global {
  interface Window {
    SpeechRecognition: new () => SpeechRecognitionInstance
    webkitSpeechRecognition: new () => SpeechRecognitionInstance
  }
}

export interface UseVoiceInputReturn {
  isRecording: boolean
  transcript: string
  interimTranscript: string
  startRecording: () => void
  stopRecording: () => string
  cancelRecording: () => void
  forceReleaseMic: () => void
  cleanup: () => void
  isSupported: boolean
  error: string | null
}

// iOS Safari does not support continuous mode and auto-stops after silence.
// We detect iOS to handle this gracefully with a restart limit.
const isIOS =
  typeof navigator !== 'undefined' &&
  /iPad|iPhone|iPod/.test(navigator.userAgent)

// iOS Safari auto-stops recognition after each silence gap. Each restart counts.
// 5 was too low -- users pausing between sentences exhausted it in under a minute.
// 30 allows ~2-3 minutes of natural speech with pauses.
const MAX_RESTART_ATTEMPTS = 30

export function useVoiceInput(): UseVoiceInputReturn {
  const [isRecording, setIsRecording] = useState(false)
  const [transcript, setTranscript] = useState('')
  const [interimTranscript, setInterimTranscript] = useState('')
  const [error, setError] = useState<string | null>(null)

  const recognitionRef = useRef<SpeechRecognitionInstance | null>(null)
  const isRecordingRef = useRef(false)
  const mountedRef = useRef(true)
  const transcriptRef = useRef('')
  // Accumulated final text from previous recognition sessions (iOS restarts).
  // When iOS auto-stops and restarts, each new session has fresh results.
  // We snapshot the current transcriptRef into accumulatedRef so that
  // the next onresult can append to it instead of overwriting.
  const accumulatedRef = useRef('')
  const restartCountRef = useRef(0)

  const isSupported =
    typeof window !== 'undefined' &&
    ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window)

  // Create a FRESH SpeechRecognition instance every time recording starts.
  // Never reuse instances -- stale onend closures cause ghost instances that
  // compete for the mic and lock it permanently on iOS.
  const createRecognition = useCallback((): SpeechRecognitionInstance | null => {
    if (!isSupported) return null

    const SpeechRecognitionCtor =
      window.SpeechRecognition || window.webkitSpeechRecognition
    const recognition = new SpeechRecognitionCtor()

    // iOS Safari does not support continuous mode -- disable to prevent thrashing
    recognition.continuous = !isIOS
    recognition.interimResults = true
    recognition.lang = 'en-US'

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      if (!mountedRef.current) return
      // CRITICAL: Ignore events from stale instances.
      // After stop+restart, a dead instance may still fire callbacks.
      if (recognitionRef.current !== recognition) return

      let sessionFinalText = ''
      let interimText = ''

      for (let i = 0; i < event.results.length; i++) {
        const result = event.results[i]
        if (result.isFinal) {
          sessionFinalText += result[0].transcript
        } else {
          interimText += result[0].transcript
        }
      }

      // On iOS (continuous=false), recognition auto-stops after silence
      // and restarts via onend. Each restart creates a new recognition
      // session with fresh results, so we must ACCUMULATE final text
      // across restarts rather than overwriting.
      if (sessionFinalText) {
        // Only append genuinely new final text (avoid duplicates from
        // the same recognition session re-firing onresult).
        transcriptRef.current = accumulatedRef.current + sessionFinalText
      }
      setTranscript(transcriptRef.current)
      setInterimTranscript(interimText)
    }

    recognition.onerror = (event: Event & { error: string }) => {
      if (!mountedRef.current) return
      // 'aborted' is expected when we call stop/abort, not a real error
      if (event.error === 'aborted') return
      // Ignore events from stale instances
      if (recognitionRef.current !== recognition) return

      setError(event.error)
      setIsRecording(false)
      isRecordingRef.current = false
      // Destroy the instance so iOS fully releases the mic on error
      recognitionRef.current = null
    }

    recognition.onend = () => {
      if (!mountedRef.current) return

      // CRITICAL: Ignore events from stale/ghost instances.
      // Without this check, the following race condition locks the mic:
      //   1. iOS auto-stops recognition, onend fires on instance A
      //   2. User taps Send -> stopRecording aborts A, nulls ref
      //   3. User taps Talk -> creates instance B, sets isRecordingRef=true
      //   4. Instance A's onend fires (async from step 2's abort)
      //   5. Sees isRecordingRef=true, restarts instance A via closure
      //   6. Now A and B both hold the mic -> iOS locks up
      if (recognitionRef.current !== recognition) return

      // If the user has stopped recording (isRecordingRef is false),
      // do NOT restart. Just clean up and exit.
      if (!isRecordingRef.current) {
        if (mountedRef.current) {
          setIsRecording(false)
        }
        return
      }

      // Still supposed to be recording -- restart to handle silence
      // auto-stop (especially on iOS), but respect the restart limit.
      // Snapshot accumulated text so the next onresult can append to it.
      accumulatedRef.current = transcriptRef.current
      if (restartCountRef.current < MAX_RESTART_ATTEMPTS) {
        restartCountRef.current++
        try {
          recognition.start()
        } catch {
          isRecordingRef.current = false
          // Destroy the instance to release the mic on failed restart
          recognitionRef.current = null
          if (mountedRef.current) {
            setIsRecording(false)
          }
        }
      } else {
        // Max restarts reached -- stop to prevent infinite loop
        isRecordingRef.current = false
        // Destroy the instance so iOS fully releases the mic
        recognitionRef.current = null
        if (mountedRef.current) {
          setIsRecording(false)
        }
      }
    }

    return recognition
  }, [isSupported])

  const startRecording = useCallback(() => {
    // Force-kill any existing instance FIRST to prevent ghost instances.
    // On iOS, a lingering SpeechRecognition can hold the mic even after abort()
    // if the object isn't dereferenced for GC.
    if (recognitionRef.current) {
      try {
        recognitionRef.current.abort()
      } catch {
        // Already stopped
      }
      recognitionRef.current = null
    }

    const recognition = createRecognition()
    if (!recognition) return

    recognitionRef.current = recognition

    setError(null)
    setTranscript('')
    setInterimTranscript('')
    transcriptRef.current = ''
    accumulatedRef.current = ''
    restartCountRef.current = 0
    isRecordingRef.current = true
    setIsRecording(true)

    try {
      recognition.start()
    } catch {
      // Mic may still be locked by a dying instance. Wait longer and retry.
      setTimeout(() => {
        try {
          recognition.start()
        } catch {
          if (mountedRef.current) {
            setError('Failed to start speech recognition')
            setIsRecording(false)
          }
          isRecordingRef.current = false
          recognitionRef.current = null
        }
      }, 200)
    }
  }, [createRecognition])

  const stopRecording = useCallback((): string => {
    // Capture the transcript BEFORE doing anything else
    const finalTranscript = transcriptRef.current

    // Signal that we intend to stop - prevents onend from restarting
    isRecordingRef.current = false
    setIsRecording(false)
    setInterimTranscript('')

    const recognition = recognitionRef.current
    if (recognition) {
      try {
        // Use abort() instead of stop() to immediately release the microphone.
        // stop() is async and keeps the mic locked while it processes remaining audio.
        // We already have the accumulated transcript in transcriptRef, so we don't
        // need the final onresult that stop() would trigger.
        recognition.abort()
      } catch {
        // Already stopped
      }
      // Destroy the instance so iOS fully releases the system mic.
      // Without this, the mic stays locked even after abort() and other
      // apps (like Nexus v1) can't record until the user force-quits.
      // A fresh instance is created automatically on next startRecording().
      recognitionRef.current = null
    }

    return finalTranscript
  }, [])

  const cancelRecording = useCallback(() => {
    isRecordingRef.current = false
    setIsRecording(false)
    setTranscript('')
    setInterimTranscript('')
    transcriptRef.current = ''
    accumulatedRef.current = ''

    const recognition = recognitionRef.current
    if (recognition) {
      try {
        recognition.abort()
      } catch {
        // Already stopped
      }
      // Destroy instance to fully release the mic on iOS
      recognitionRef.current = null
    }
  }, [])

  // Force-release the microphone regardless of current state.
  // Use this when you need to guarantee the mic is freed (e.g., before
  // another app needs it).
  const forceReleaseMic = useCallback(() => {
    isRecordingRef.current = false
    setIsRecording(false)
    setInterimTranscript('')

    const recognition = recognitionRef.current
    if (recognition) {
      try {
        recognition.abort()
      } catch {
        // Already stopped
      }
      // Destroy the instance so a fresh one is created next time
      recognitionRef.current = null
    }
  }, [])

  // Full cleanup: abort recognition, null out the instance, clear all state.
  // Call this on component unmount.
  const cleanup = useCallback(() => {
    isRecordingRef.current = false
    setIsRecording(false)
    setTranscript('')
    setInterimTranscript('')
    transcriptRef.current = ''
    accumulatedRef.current = ''

    const recognition = recognitionRef.current
    if (recognition) {
      try {
        recognition.abort()
      } catch {
        // Already stopped
      }
      recognitionRef.current = null
    }
  }, [])

  // Release the microphone when the app goes to background.
  // On iOS, backgrounding doesn't unmount components or close the webview,
  // so the SpeechRecognition stays active and locks the system mic.
  // Other apps (including Nexus v1) can't record until we release it.
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'hidden' && isRecordingRef.current) {
        // Force-release: abort + destroy the instance so iOS fully frees the mic
        isRecordingRef.current = false
        setIsRecording(false)
        setInterimTranscript('')
        const recognition = recognitionRef.current
        if (recognition) {
          try {
            recognition.abort()
          } catch {
            // Already stopped
          }
          // Destroy instance -- iOS only truly releases the mic when the
          // SpeechRecognition object is garbage collected
          recognitionRef.current = null
        }
      }
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
  }, [])

  // Track mounted state and clean up on unmount
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      isRecordingRef.current = false
      const recognition = recognitionRef.current
      if (recognition) {
        try {
          recognition.abort()
        } catch {
          // Already stopped
        }
        // Null out the instance so the mic is fully released
        recognitionRef.current = null
      }
    }
  }, [])

  return {
    isRecording,
    transcript,
    interimTranscript,
    startRecording,
    stopRecording,
    cancelRecording,
    forceReleaseMic,
    cleanup,
    isSupported,
    error,
  }
}
