import { registerPlugin } from '@capacitor/core'
import type { PluginListenerHandle } from '@capacitor/core'

export interface SpeechRecognitionPlugin {
  start(options?: { lang?: string }): Promise<void>
  stop(): Promise<{ transcript: string }>
  cancel(): Promise<void>
  checkPermissions(): Promise<{ speech: string; microphone: string }>
  requestPermissions(): Promise<{ speech: string; microphone: string }>
  addListener(
    eventName: 'result',
    listenerFunc: (data: { transcript: string; isFinal: boolean }) => void
  ): Promise<PluginListenerHandle>
  addListener(
    eventName: 'error',
    listenerFunc: (data: { error: string }) => void
  ): Promise<PluginListenerHandle>
  addListener(
    eventName: 'end',
    listenerFunc: () => void
  ): Promise<PluginListenerHandle>
}

const SpeechRecognition = registerPlugin<SpeechRecognitionPlugin>('SpeechRecognition')

export default SpeechRecognition
