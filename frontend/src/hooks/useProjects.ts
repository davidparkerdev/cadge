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
    fetch(`${SERVICE_MANAGER_URL}/api/services/catalog`)
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
      .catch(() => {
        // Service manager might not be running
        setProjects([])
      })
      .finally(() => setIsLoading(false))
  }, [])

  return { projects, isLoading }
}
