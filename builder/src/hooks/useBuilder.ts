import { useContext } from 'react'

import { BuilderContext } from '../contexts/builderContext'

export function useBuilder() {
  const controller = useContext(BuilderContext)
  if (!controller) throw new Error('useBuilder must be used inside BuilderProvider')
  return controller
}
