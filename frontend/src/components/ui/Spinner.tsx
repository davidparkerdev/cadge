import { type HTMLAttributes } from 'react'
import { cn } from '../../lib/cn'

export interface SpinnerProps extends HTMLAttributes<HTMLDivElement> {
  size?: 'sm' | 'md' | 'lg'
}

export function Spinner({ className, size = 'md', ...props }: SpinnerProps) {
  const sizeClasses = {
    sm: 'w-4 h-4',
    md: 'w-6 h-6',
    lg: 'w-8 h-8',
  }

  return (
    <div
      className={cn(
        'border-2 border-accent border-t-transparent rounded-full animate-spin',
        sizeClasses[size],
        className
      )}
      {...props}
    />
  )
}
