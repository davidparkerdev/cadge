import { useState, useRef, useCallback, useEffect } from 'react'
import { log } from '../lib/logger'

/** Generate a unique ID -- crypto.randomUUID requires secure context (HTTPS) */
function uniqueId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    try {
      return crypto.randomUUID()
    } catch {
      // Not in a secure context (HTTP) -- fall through
    }
  }
  // Fallback: timestamp + random
  return `${Date.now()}-${Math.random().toString(36).slice(2, 11)}`
}

export interface StagedImage {
  id: string
  file: File
  previewUrl: string
  base64?: string
}

interface UseImageAttachmentReturn {
  images: StagedImage[]
  addImages: (files: FileList | File[]) => Promise<void>
  removeImage: (id: string) => void
  clearImages: () => void
  openPicker: () => void
  /** Ref for a hidden <input type="file" accept="image/*" multiple /> that the consumer must render. */
  inputRef: React.RefObject<HTMLInputElement | null>
  error: string | null
}

const MAX_IMAGES = 5

// iOS Safari canvas limit is ~16.7 megapixels. Cap to stay well under.
const MAX_CANVAS_PIXELS = 16_000_000

/** Image file extensions for iOS fallback when file.type is empty */
const IMAGE_EXTENSIONS = /\.(jpe?g|png|gif|webp|heic|heif|bmp|tiff?)$/i

/** Check if a file is an image -- handles iOS Safari empty file.type bug */
function isImageFile(file: File): boolean {
  if (file.type && file.type.startsWith('image/')) return true
  // iOS Safari sometimes returns empty type for photos from library
  if (file.name && IMAGE_EXTENSIONS.test(file.name)) return true
  return false
}

/** Read a file directly as a data URL (base64) without any processing */
function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onloadend = () => {
      if (typeof reader.result === 'string') {
        resolve(reader.result)
      } else {
        reject(new Error('Failed to read file'))
      }
    }
    reader.onerror = () => reject(new Error('Failed to read file'))
    reader.readAsDataURL(file)
  })
}

/**
 * Load an image source (File) into an ImageBitmap or HTMLImageElement.
 * Prefers createImageBitmap (handles HEIC natively on iOS 15+),
 * falls back to HTMLImageElement for older browsers.
 */
async function loadImage(file: File): Promise<{ source: CanvasImageSource; width: number; height: number }> {
  // Try createImageBitmap first -- handles more formats (HEIC) and is async-native
  if (typeof createImageBitmap === 'function') {
    try {
      const bitmap = await createImageBitmap(file)
      return { source: bitmap, width: bitmap.width, height: bitmap.height }
    } catch {
      // Fall through to Image element approach
    }
  }

  // Fallback: load via HTMLImageElement + object URL
  return new Promise((resolve, reject) => {
    const img = new Image()
    const objectUrl = URL.createObjectURL(file)

    const timeout = setTimeout(() => {
      URL.revokeObjectURL(objectUrl)
      reject(new Error('Image load timed out'))
    }, 15000)

    img.onload = () => {
      clearTimeout(timeout)
      URL.revokeObjectURL(objectUrl)
      resolve({ source: img, width: img.width, height: img.height })
    }

    img.onerror = () => {
      clearTimeout(timeout)
      URL.revokeObjectURL(objectUrl)
      reject(new Error('Failed to load image'))
    }

    img.src = objectUrl
  })
}

/**
 * Compress and resize an image file to JPEG.
 * Scales down to fit within iOS canvas pixel limit and maxSize.
 */
async function compressImage(
  file: File,
  maxSize = 1920,
  quality = 0.85
): Promise<{ base64: string; blob: Blob }> {
  const { source, width: origW, height: origH } = await loadImage(file)

  let width = origW
  let height = origH

  // Scale down if larger than maxSize on either dimension
  if (width > maxSize || height > maxSize) {
    const ratio = Math.min(maxSize / width, maxSize / height)
    width = Math.round(width * ratio)
    height = Math.round(height * ratio)
  }

  // iOS Safari canvas pixel limit -- scale further if needed
  const pixels = width * height
  if (pixels > MAX_CANVAS_PIXELS) {
    const ratio = Math.sqrt(MAX_CANVAS_PIXELS / pixels)
    width = Math.round(width * ratio)
    height = Math.round(height * ratio)
  }

  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height

  const ctx = canvas.getContext('2d')
  if (!ctx) {
    throw new Error('Failed to get canvas context')
  }

  ctx.drawImage(source, 0, 0, width, height)

  // Close bitmap to free memory if applicable
  if ('close' in source && typeof source.close === 'function') {
    (source as ImageBitmap).close()
  }

  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (!blob) {
          reject(new Error('Failed to compress image'))
          return
        }

        const reader = new FileReader()
        reader.onloadend = () => {
          resolve({
            base64: reader.result as string,
            blob,
          })
        }
        reader.onerror = () => reject(new Error('Failed to read compressed image'))
        reader.readAsDataURL(blob)
      },
      'image/jpeg',
      quality
    )
  })
}

/**
 * Hook for selecting, staging, and managing image attachments for messages.
 *
 * The consumer is responsible for rendering a hidden file input using the returned
 * inputRef. Example:
 *
 * ```tsx
 * <input
 *   ref={inputRef}
 *   type="file"
 *   accept="image/*"
 *   multiple
 *   hidden
 *   onChange={(e) => e.target.files && addImages(e.target.files)}
 * />
 * ```
 */
export function useImageAttachment(): UseImageAttachmentReturn {
  const [images, setImages] = useState<StagedImage[]>([])
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const errorTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Auto-clear error after 3 seconds
  useEffect(() => {
    if (error) {
      if (errorTimerRef.current) clearTimeout(errorTimerRef.current)
      errorTimerRef.current = setTimeout(() => setError(null), 3000)
    }
    return () => {
      if (errorTimerRef.current) clearTimeout(errorTimerRef.current)
    }
  }, [error])

  // Revoke all object URLs on unmount
  useEffect(() => {
    return () => {
      setImages((prev) => {
        prev.forEach((img) => URL.revokeObjectURL(img.previewUrl))
        return []
      })
    }
  }, [])

  const addImages = useCallback(
    async (files: FileList | File[]) => {
      const fileArray = Array.from(files)

      // Filter to only image files (handles iOS empty file.type)
      const imageFiles = fileArray.filter(isImageFile)
      if (imageFiles.length === 0) {
        setError('No valid image files selected')
        return
      }

      // Determine how many we can actually add
      const currentCount = images.length
      const remaining = MAX_IMAGES - currentCount
      if (remaining <= 0) {
        setError('Maximum 5 images allowed')
        return
      }

      const filesToProcess = imageFiles.slice(0, remaining)
      if (imageFiles.length > remaining) {
        setError('Maximum 5 images allowed')
      }

      const newImages: StagedImage[] = []
      let failCount = 0

      for (const file of filesToProcess) {
        const previewUrl = URL.createObjectURL(file)
        log.info('image', `Processing: ${file.name} (${file.type || 'unknown type'}, ${(file.size / 1024).toFixed(0)}KB)`)
        try {
          let base64: string
          try {
            const result = await compressImage(file)
            base64 = result.base64
            log.info('image', `Compressed: ${file.name}`)
          } catch (compressErr) {
            log.warn('image', `Compression failed for ${file.name}, using raw base64`, compressErr)
            base64 = await readFileAsBase64(file)
            log.info('image', `Raw base64 read OK: ${file.name} (${(base64.length / 1024).toFixed(0)}KB)`)
          }

          newImages.push({
            id: uniqueId(),
            file,
            previewUrl,
            base64,
          })
        } catch (err) {
          URL.revokeObjectURL(previewUrl)
          failCount++
          const errMsg = err instanceof Error ? err.message : String(err)
          log.error('image', `Failed to process ${file.name}: ${errMsg}`, err)
        }
      }

      if (failCount > 0 && newImages.length === 0) {
        const errDetail = `Failed to process ${failCount} image${failCount > 1 ? 's' : ''} - check console for details`
        setError(errDetail)
        log.error('image', errDetail)
      }

      if (newImages.length > 0) {
        setImages((prev) => [...prev, ...newImages])
      }

      // Reset the input so the same file can be selected again
      if (inputRef.current) {
        inputRef.current.value = ''
      }
    },
    [images.length]
  )

  const removeImage = useCallback((id: string) => {
    setImages((prev) => {
      const target = prev.find((img) => img.id === id)
      if (target) {
        URL.revokeObjectURL(target.previewUrl)
      }
      return prev.filter((img) => img.id !== id)
    })
  }, [])

  const clearImages = useCallback(() => {
    setImages((prev) => {
      prev.forEach((img) => URL.revokeObjectURL(img.previewUrl))
      return []
    })
  }, [])

  const openPicker = useCallback(() => {
    inputRef.current?.click()
  }, [])

  return {
    images,
    addImages,
    removeImage,
    clearImages,
    openPicker,
    inputRef,
    error,
  }
}
