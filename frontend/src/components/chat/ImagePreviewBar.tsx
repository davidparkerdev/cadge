import { Xmark } from 'iconoir-react'
import { cn } from '../../lib/cn'
import type { StagedImage } from '../../hooks/useImageAttachment'

interface ImagePreviewBarProps {
  images: StagedImage[]
  onRemove: (id: string) => void
}

export function ImagePreviewBar({ images, onRemove }: ImagePreviewBarProps) {
  if (images.length === 0) return null

  return (
    <div
      className={cn(
        'flex items-center gap-2 px-3 py-2',
        'border-t border-border bg-surface-secondary',
        'overflow-x-auto',
        '[&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none]'
      )}
    >
      {images.map((image) => (
        <div key={image.id} className="relative flex-shrink-0">
          <img
            src={image.previewUrl}
            alt={image.file.name}
            className="w-14 h-14 rounded-lg object-cover border border-border"
          />
          <button
            type="button"
            onClick={() => onRemove(image.id)}
            className={cn(
              'absolute -top-1 -right-1 w-5 h-5 rounded-full',
              'bg-red-500 flex items-center justify-center',
              'hover:bg-red-600 active:bg-red-700 transition-colors',
              'touch-manipulation'
            )}
            aria-label={`Remove ${image.file.name}`}
          >
            <Xmark className="w-3 h-3 text-white" />
          </button>
        </div>
      ))}
    </div>
  )
}
