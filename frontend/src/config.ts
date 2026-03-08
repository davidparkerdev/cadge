function resolveServiceUrl(port: number): string {
  const host = window.location.hostname
  const proto = window.location.protocol
  const tsPort = host.endsWith('.ts.net') ? port + 10000 : port
  return `${proto}//${host}:${tsPort}`
}

export const API_URL =
  import.meta.env.VITE_API_URL || resolveServiceUrl(33401)
