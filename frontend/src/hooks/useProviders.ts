import { useState, useEffect, useCallback } from 'react'
import type { ProviderInfo, ProviderModel, ProviderStatus } from '../api/types'
import { listProviders, getProviderModels, getProviderStatus } from '../api/client'

export function useProviders() {
  const [providers, setProviders] = useState<ProviderInfo[]>([])
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    listProviders()
      .then(setProviders)
      .catch(() => setProviders([]))
      .finally(() => setIsLoading(false))
  }, [])

  return { providers, isLoading }
}

export function useProviderModels(providerId: string | null) {
  const [models, setModels] = useState<ProviderModel[]>([])
  const [isLoading, setIsLoading] = useState(false)

  const fetchModels = useCallback(async (id: string) => {
    setIsLoading(true)
    try {
      const result = await getProviderModels(id)
      setModels(result)
    } catch {
      setModels([])
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    if (providerId) {
      fetchModels(providerId)
    } else {
      setModels([])
    }
  }, [providerId, fetchModels])

  return { models, isLoading, refresh: () => providerId && fetchModels(providerId) }
}

export function useProviderStatus(providerId: string | null) {
  const [status, setStatus] = useState<ProviderStatus | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  useEffect(() => {
    if (!providerId) {
      setStatus(null)
      return
    }
    setIsLoading(true)
    getProviderStatus(providerId)
      .then(setStatus)
      .catch(() => setStatus({ status: 'error', detail: 'Failed to check status' }))
      .finally(() => setIsLoading(false))
  }, [providerId])

  return { status, isLoading }
}
