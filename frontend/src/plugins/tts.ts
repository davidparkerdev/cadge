import { registerPlugin } from '@capacitor/core'
import type { PluginListenerHandle } from '@capacitor/core'

export interface TTSPlugin {
  speak(options: {
    text: string
    rate?: number
    pitch?: number
    offset?: number
    voiceId?: string
  }): Promise<void>
  pause(): Promise<void>
  resume(): Promise<void>
  stop(): Promise<void>
  getVoices(): Promise<{
    voices: Array<{
      id: string
      name: string
      lang: string
      quality: number
    }>
  }>
  addListener(
    eventName: 'start',
    listenerFunc: () => void
  ): Promise<PluginListenerHandle>
  addListener(
    eventName: 'end',
    listenerFunc: () => void
  ): Promise<PluginListenerHandle>
  addListener(
    eventName: 'pause',
    listenerFunc: () => void
  ): Promise<PluginListenerHandle>
  addListener(
    eventName: 'resume',
    listenerFunc: () => void
  ): Promise<PluginListenerHandle>
  addListener(
    eventName: 'boundary',
    listenerFunc: (data: {
      charIndex: number
      charLength: number
      progress: number
    }) => void
  ): Promise<PluginListenerHandle>
}

const TTS = registerPlugin<TTSPlugin>('TTS')

export default TTS
