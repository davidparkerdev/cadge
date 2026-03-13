import { Routes, Route } from 'react-router-dom'
import { AppLayout } from './components/layout/AppLayout'
import { ChatView } from './components/chat/ChatView'
import { HomeView } from './components/home/HomeView'
import { ErrorBoundary } from './components/ErrorBoundary'

export function App() {
  return (
    <ErrorBoundary>
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/" element={<HomeView />} />
          <Route path="/session/:id" element={<ChatView />} />
        </Route>
      </Routes>
    </ErrorBoundary>
  )
}
