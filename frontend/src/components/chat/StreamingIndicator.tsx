export function StreamingIndicator() {
  return (
    <div className="flex items-center gap-1.5 px-4 py-2">
      <div className="flex gap-1">
        <span className="w-1.5 h-1.5 rounded-full bg-accent animate-bounce [animation-delay:0ms]" />
        <span className="w-1.5 h-1.5 rounded-full bg-accent animate-bounce [animation-delay:150ms]" />
        <span className="w-1.5 h-1.5 rounded-full bg-accent animate-bounce [animation-delay:300ms]" />
      </div>
      <span className="text-xs text-text-secondary ml-1">Thinking...</span>
    </div>
  )
}
