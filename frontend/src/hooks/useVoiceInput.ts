import { useState, useRef, useCallback, useEffect } from 'react'
import { Capacitor } from '@capacitor/core'
import SpeechRecognition from '../plugins/speech-recognition'

// Web Speech API types (desktop browser fallback only)
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

const isNative = Capacitor.isNativePlatform()

// ---------------------------------------------------------------------------
// Native implementation (Capacitor / iOS)
// Uses SFSpeechRecognizer via native plugin. No ghost instances, no mic locks,
// no auto-stop races. Apple's Speech framework handles all of this properly.
// ---------------------------------------------------------------------------

function useNativeVoiceInput(): UseVoiceInputReturn {
  const [isRecording, setIsRecording] = useState(false)
  const [transcript, setTranscript] = useState('')
  const [interimTranscript, setInterimTranscript] = useState('')
  const [error, setError] = useState<string | null>(null)
  const isRecordingRef = useRef(false)
  const transcriptRef = useRef('')

  // Set up native plugin listeners
  useEffect(() => {
    const listeners: Array<{ remove: () => void }> = []

    const setup = async () => {
      const resultListener = await SpeechRecognition.addListener(
        'result',
        (data) => {
          transcriptRef.current = data.transcript
          if (data.isFinal) {
            setTranscript(data.transcript)
            setInterimTranscript('')
          } else {
            setInterimTranscript(data.transcript)
          }
        }
      )
      listeners.push(resultListener)

      const endListener = await SpeechRecognition.addListener('end', () => {
        isRecordingRef.current = false
        setIsRecording(false)
        setInterimTranscript('')
      })
      listeners.push(endListener)

      const errorListener = await SpeechRecognition.addListener(
        'error',
        (data) => {
          setError(data.error)
          isRecordingRef.current = false
          setIsRecording(false)
        }
      )
      listeners.push(errorListener)
    }

    setup()

    return () => {
      listeners.forEach((l) => l.remove())
      if (isRecordingRef.current) {
        SpeechRecognition.cancel()
      }
    }
  }, [])

  const startRecording = useCallback(async () => {
    setError(null)
    setTranscript('')
    setInterimTranscript('')
    transcriptRef.current = ''

    try {
      // Check/request permissions
      const perms = await SpeechRecognition.checkPermissions()
      if (perms.speech !== 'granted' || perms.microphone !== 'granted') {
        const requested = await SpeechRecognition.requestPermissions()
        if (
          requested.speech !== 'granted' ||
          requested.microphone !== 'granted'
        ) {
          setError('Microphone or speech recognition permission denied')
          return
        }
      }

      await SpeechRecognition.start({ lang: 'en-US' })
      isRecordingRef.current = true
      setIsRecording(true)
    } catch (err) {
      setError(
        err instanceof Error ? err.message : 'Failed to start recognition'
      )
    }
  }, [])

  const stopRecording = useCallback((): string => {
    const currentTranscript = transcriptRef.current
    isRecordingRef.current = false
    setIsRecording(false)
    setInterimTranscript('')

    SpeechRecognition.stop().catch(() => {})
    return currentTranscript
  }, [])

  const cancelRecording = useCallback(() => {
    isRecordingRef.current = false
    setIsRecording(false)
    setTranscript('')
    setInterimTranscript('')
    transcriptRef.current = ''
    SpeechRecognition.cancel().catch(() => {})
  }, [])

  const forceReleaseMic = useCallback(() => {
    isRecordingRef.current = false
    setIsRecording(false)
    setInterimTranscript('')
    SpeechRecognition.cancel().catch(() => {})
  }, [])

  const cleanup = useCallback(() => {
    isRecordingRef.current = false
    setIsRecording(false)
    setTranscript('')
    setInterimTranscript('')
    transcriptRef.current = ''
    SpeechRecognition.cancel().catch(() => {})
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
    isSupported: true,
    error,
  }
}

// ---------------------------------------------------------------------------
// Web Speech API implementation (desktop browsers only)
// No iOS workarounds needed -- iOS uses native plugin above.
// Simple, clean implementation for Chrome/Firefox/Edge on desktop.
// ---------------------------------------------------------------------------

function useWebVoiceInput(): UseVoiceInputReturn {
  const [isRecording, setIsRecording] = useState(false)
  const [transcript, setTranscript] = useState('')
  const [interimTranscript, setInterimTranscript] = useState('')
  const [error, setError] = useState<string | null>(null)

  const recognitionRef = useRef<SpeechRecognitionInstance | null>(null)
  const isRecordingRef = useRef(false)
  const mountedRef = useRef(true)
  const transcriptRef = useRef('')

  const isSupported =
    typeof window !== 'undefined' &&
    ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window)

  const startRecording = useCallback(() => {
    if (!isSupported) return

    // Clean up any prior instance
    if (recognitionRef.current) {
      try {
        recognitionRef.current.abort()
      } catch {
        // Already stopped
      }
      recognitionRef.current = null
    }

    const SpeechRecognitionCtor =
      window.SpeechRecognition || window.webkitSpeechRecognition
    const recognition = new SpeechRecognitionCtor()

    recognition.continuous = true
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

      if (finalText) {
        transcriptRef.current = finalText
      }
      setTranscript(transcriptRef.current)
      setInterimTranscript(interimText)
    }

    recognition.onerror = (event: Event & { error: string }) => {
      if (!mountedRef.current) return
      if (event.error === 'aborted') return

      setError(event.error)
      setIsRecording(false)
      isRecordingRef.current = false
      recognitionRef.current = null
    }

    recognition.onend = () => {
      if (!mountedRef.current) return
      if (!isRecordingRef.current) return

      // Desktop browsers: recognition ended unexpectedly, stop cleanly
      isRecordingRef.current = false
      setIsRecording(false)
    }

    recognitionRef.current = recognition
    setError(null)
    setTranscript('')
    setInterimTranscript('')
    transcriptRef.current = ''
    isRecordingRef.current = true
    setIsRecording(true)

    try {
      recognition.start()
    } catch {
      setError('Failed to start speech recognition')
      setIsRecording(false)
      isRecordingRef.current = false
      recognitionRef.current = null
    }
  }, [isSupported])

  const stopRecording = useCallback((): string => {
    const finalTranscript = transcriptRef.current
    isRecordingRef.current = false
    setIsRecording(false)
    setInterimTranscript('')

    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop()
      } catch {
        // Already stopped
      }
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

    if (recognitionRef.current) {
      try {
        recognitionRef.current.abort()
      } catch {
        // Already stopped
      }
      recognitionRef.current = null
    }
  }, [])

  const forceReleaseMic = useCallback(() => {
    isRecordingRef.current = false
    setIsRecording(false)
    setInterimTranscript('')

    if (recognitionRef.current) {
      try {
        recognitionRef.current.abort()
      } catch {
        // Already stopped
      }
      recognitionRef.current = null
    }
  }, [])

  const cleanup = useCallback(() => {
    isRecordingRef.current = false
    setIsRecording(false)
    setTranscript('')
    setInterimTranscript('')
    transcriptRef.current = ''

    if (recognitionRef.current) {
      try {
        recognitionRef.current.abort()
      } catch {
        // Already stopped
      }
      recognitionRef.current = null
    }
  }, [])

  // Clean up on unmount
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      isRecordingRef.current = false
      if (recognitionRef.current) {
        try {
          recognitionRef.current.abort()
        } catch {
          // Already stopped
        }
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

// ---------------------------------------------------------------------------
// Export: pick implementation at module load time (not at render time).
// This satisfies React's rules of hooks -- the same function is always called.
// ---------------------------------------------------------------------------

export const useVoiceInput: () => UseVoiceInputReturn = isNative
  ? useNativeVoiceInput
  : useWebVoiceInput
