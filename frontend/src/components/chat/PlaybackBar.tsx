import {
  SoundHigh,
  Backward15Seconds,
  Forward15Seconds,
  Pause,
  Play,
  Square,
} from 'iconoir-react'
import { cn } from '../../lib/cn'

interface PlaybackBarProps {
  isSpeaking: boolean
  isPaused: boolean
  progress: number
  onPause: () => void
  onResume: () => void
  onStop: () => void
  onSkipBack: () => void
  onSkipForward: () => void
}

export function PlaybackBar({
  isSpeaking,
  isPaused,
  progress,
  onPause,
  onResume,
  onStop,
  onSkipBack,
  onSkipForward,
}: PlaybackBarProps) {
  if (!isSpeaking && !isPaused) return null

  return (
    <div className="bg-surface-secondary border-t border-border">
      <div className="flex items-center gap-3 px-4 py-2">
        {/* Speaker icon */}
        <SoundHigh className="h-5 w-5 shrink-0 text-accent" />

        {/* Center controls */}
        <div className="flex flex-1 items-center justify-center gap-2">
          <button
            type="button"
            onClick={onSkipBack}
            className={cn(
              'flex h-10 w-10 items-center justify-center rounded-full',
              'text-text-secondary active:text-text-primary',
              'touch-manipulation'
            )}
            aria-label="Skip back 15 seconds"
          >
            <Backward15Seconds className="h-5 w-5" />
          </button>

          <button
            type="button"
            onClick={isPaused ? onResume : onPause}
            className={cn(
              'flex h-10 w-10 items-center justify-center rounded-full',
              'bg-surface-tertiary text-text-primary active:bg-accent/20',
              'touch-manipulation'
            )}
            aria-label={isPaused ? 'Resume playback' : 'Pause playback'}
          >
            {isPaused ? (
              <Play className="h-5 w-5" />
            ) : (
              <Pause className="h-5 w-5" />
            )}
          </button>

          <button
            type="button"
            onClick={onSkipForward}
            className={cn(
              'flex h-10 w-10 items-center justify-center rounded-full',
              'text-text-secondary active:text-text-primary',
              'touch-manipulation'
            )}
            aria-label="Skip forward 15 seconds"
          >
            <Forward15Seconds className="h-5 w-5" />
          </button>
        </div>

        {/* Stop button */}
        <button
          type="button"
          onClick={onStop}
          className={cn(
            'flex h-10 w-10 items-center justify-center rounded-full',
            'text-red-400 active:text-red-300',
            'touch-manipulation'
          )}
          aria-label="Stop playback"
        >
          <Square className="h-4 w-4" />
        </button>
      </div>

      {/* Progress bar */}
      <div className="h-0.5 bg-accent/30">
        <div
          className="h-0.5 bg-accent transition-[width] duration-300 ease-linear"
          style={{ width: `${Math.min(progress * 100, 100)}%` }}
        />
      </div>
    </div>
  )
}
