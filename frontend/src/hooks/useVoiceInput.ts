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
  isSupported: boolean
  error: string | null
}

// iOS Safari does not support continuous mode and auto-stops after silence.
// We detect iOS to handle this gracefully with a restart limit.
const isIOS =
  typeof navigator !== 'undefined' &&
  /iPad|iPhone|iPod/.test(navigator.userAgent)

const MAX_RESTART_ATTEMPTS = 5

export function useVoiceInput(): UseVoiceInputReturn {
  const [isRecording, setIsRecording] = useState(false)
  const [transcript, setTranscript] = useState('')
  const [interimTranscript, setInterimTranscript] = useState('')
  const [error, setError] = useState<string | null>(null)

  const recognitionRef = useRef<SpeechRecognitionInstance | null>(null)
  const isRecordingRef = useRef(false)
  const mountedRef = useRef(true)
  const transcriptRef = useRef('')
  const restartCountRef = useRef(0)

  const isSupported =
    typeof window !== 'undefined' &&
    ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window)

  const getRecognition = useCallback((): SpeechRecognitionInstance | null => {
    if (!isSupported) return null

    if (!recognitionRef.current) {
      const SpeechRecognitionCtor =
        window.SpeechRecognition || window.webkitSpeechRecognition
      const recognition = new SpeechRecognitionCtor()

      // iOS Safari does not support continuous mode -- disable to prevent thrashing
      recognition.continuous = !isIOS
      recognition.interimResults = true
      recognition.lang = 'en-US'

      recognition.onresult = (event: SpeechRecognitionEvent) => {
        if (!mountedRef.current) return

        let finalText = ''
        let interimText = ''

        for (let i = 0; i < event.results.length; i++) {
          const result = event.results[i]
          if (result.isFinal) {
            finalText += result[0].transcript
          } else {
            interimText += result[0].transcript
          }
        }

        transcriptRef.current = finalText
        setTranscript(finalText)
        setInterimTranscript(interimText)
      }

      recognition.onerror = (event: Event & { error: string }) => {
        if (!mountedRef.current) return
        // 'aborted' is expected when we call stop/abort, not a real error
        if (event.error === 'aborted') return

        setError(event.error)
        setIsRecording(false)
        isRecordingRef.current = false
      }

      recognition.onend = () => {
        if (!mountedRef.current) return

        // If still supposed to be recording and within restart limit,
        // restart to handle silence auto-stop (especially on iOS)
        if (
          isRecordingRef.current &&
          restartCountRef.current < MAX_RESTART_ATTEMPTS
        ) {
          restartCountRef.current++
          try {
            recognition.start()
          } catch {
            if (mountedRef.current) {
              setIsRecording(false)
            }
            isRecordingRef.current = false
          }
        } else if (isRecordingRef.current) {
          // Max restarts reached -- stop to prevent infinite loop
          isRecordingRef.current = false
          if (mountedRef.current) {
            setIsRecording(false)
          }
        }
      }

      recognitionRef.current = recognition
    }

    return recognitionRef.current
  }, [isSupported])

  const startRecording = useCallback(() => {
    const recognition = getRecognition()
    if (!recognition) return

    setError(null)
    setTranscript('')
    setInterimTranscript('')
    transcriptRef.current = ''
    restartCountRef.current = 0
    isRecordingRef.current = true
    setIsRecording(true)

    try {
      recognition.start()
    } catch {
      // If already started, abort and restart
      recognition.abort()
      setTimeout(() => {
        try {
          recognition.start()
        } catch {
          if (mountedRef.current) {
            setError('Failed to start speech recognition')
            setIsRecording(false)
          }
          isRecordingRef.current = false
        }
      }, 100)
    }
  }, [getRecognition])

  const stopRecording = useCallback((): string => {
    isRecordingRef.current = false
    setIsRecording(false)
    setInterimTranscript('')

    const recognition = recognitionRef.current
    if (recognition) {
      try {
        recognition.stop()
      } catch {
        // Already stopped
      }
    }

    return transcriptRef.current
  }, [])

  const cancelRecording = useCallback(() => {
    isRecordingRef.current = false
    setIsRecording(false)
    setTranscript('')
    setInterimTranscript('')
    transcriptRef.current = ''

    const recognition = recognitionRef.current
    if (recognition) {
      try {
        recognition.abort()
      } catch {
        // Already stopped
      }
    }
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
    isSupported,
    error,
  }
}
