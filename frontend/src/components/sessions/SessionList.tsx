import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus } from 'iconoir-react'
import { Button } from '../ui/Button'
import { Spinner } from '../ui/Spinner'
import { useSessionsContext } from '../../contexts/SessionsContext'
import { SessionItem } from './SessionItem'
import { NewSessionModal } from './NewSessionModal'

export function SessionList() {
  const navigate = useNavigate()
  const { sessions, isLoading, error, create, remove } = useSessionsContext()
  const [isNewSessionModalOpen, setIsNewSessionModalOpen] = useState(false)

  const handleNewSession = () => {
    setIsNewSessionModalOpen(true)
  }

  const handleCreateSession = async (config: {
    title?: string
    role?: string
    projectName?: string
    projectDir?: string
  }) => {
    try {
      const session = await create(config)
      setIsNewSessionModalOpen(false)
      navigate(`/session/${session.id}`)
    } catch {
      // Error is handled by the hook
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await remove(id)
      navigate('/')
    } catch {
      // Error is handled by the hook
    }
  }

  return (
    <div className="flex flex-col h-full">
      <NewSessionModal
        isOpen={isNewSessionModalOpen}
        onClose={() => setIsNewSessionModalOpen(false)}
        onCreate={handleCreateSession}
      />

      <div className="p-3">
        <Button
          variant="primary"
          size="sm"
          className="w-full"
          leftIcon={<Plus className="w-4 h-4" />}
          onClick={handleNewSession}
        >
          New Session
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto py-1">
        {isLoading && (
          <div className="flex justify-center py-8">
            <Spinner size="sm" />
          </div>
        )}

        {error && (
          <p className="text-xs text-red-400 px-4 py-2">{error}</p>
        )}

        {!isLoading && sessions.length === 0 && !error && (
          <p className="text-xs text-text-secondary px-4 py-4 text-center">
            No sessions yet
          </p>
        )}

        {sessions.map((session) => (
          <SessionItem
            key={session.id}
            session={session}
            onDelete={handleDelete}
          />
        ))}
      </div>
    </div>
  )
}
