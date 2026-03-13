import { useState, useEffect } from 'react'

export interface Project {
  id: string
  name: string
  dir: string
}

const SERVICE_MANAGER_URL = (() => {
  const host = window.location.hostname
  const port = host.endsWith('.ts.net') ? 43901 : 33901
  return `${window.location.protocol}//${host}:${port}`
})()

export function useProjects() {
  const [projects, setProjects] = useState<Project[]>([])
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    const controller = new AbortController()

    fetch(`${SERVICE_MANAGER_URL}/api/services/catalog`, {
      signal: controller.signal,
    })
      .then(res => res.json())
      .then((catalog: Array<{ id: string; name: string; repoPath: string }>) => {
        const result: Project[] = catalog
          .map(svc => ({
            id: svc.id,
            name: svc.name,
            dir: svc.repoPath,
          }))
          .sort((a, b) => a.name.localeCompare(b.name))
        setProjects(result)
      })
      .catch((err) => {
        // Ignore aborted requests (component unmounted)
        if (err.name === 'AbortError') return
        // Service manager might not be running
        setProjects([])
      })
      .finally(() => setIsLoading(false))

    return () => controller.abort()
  }, [])

  return { projects, isLoading }
}
