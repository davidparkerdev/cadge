export interface Role {
  id: string
  label: string
  description: string
  icon: string
  color: string
}

const roleColor = 'bg-gray-500/20 text-gray-300'

export const roles: Role[] = [
  { id: 'product', label: 'Product', description: 'Product management, user stories, requirements', icon: 'ClipboardCheck', color: roleColor },
  { id: 'coding', label: 'Coding', description: 'Software engineering, clean code, testing', icon: 'Code', color: roleColor },
  { id: 'writing', label: 'Writing', description: 'Technical writing, docs, communication', icon: 'EditPencil', color: roleColor },
  { id: 'deep-dive', label: 'Deep Dive', description: 'Research, investigation, thorough analysis', icon: 'Search', color: roleColor },
  { id: 'bug-fixing', label: 'Bug Fix', description: 'Debugging, root cause analysis, fixes', icon: 'WarningTriangle', color: roleColor },
  { id: 'analysis', label: 'Analysis', description: 'Data analysis, patterns, recommendations', icon: 'GraphUp', color: roleColor },
  { id: 'qa', label: 'QA', description: 'Test design, edge cases, quality assurance', icon: 'CheckCircle', color: roleColor },
  { id: 'frontend', label: 'Frontend', description: 'UX/UI design, React, Tailwind, accessibility', icon: 'DesignPencil', color: roleColor },
  { id: 'web-dev', label: 'Web Dev', description: 'Full-stack web development, APIs, infra', icon: 'Globe', color: roleColor },
  { id: 'game-dev', label: 'Game Dev', description: 'Game mechanics, systems, performance', icon: 'Gamepad', color: roleColor },
  { id: 'nextjs', label: 'Next.js', description: 'Server components, app router, SSR', icon: 'ServerConnection', color: roleColor },
]
