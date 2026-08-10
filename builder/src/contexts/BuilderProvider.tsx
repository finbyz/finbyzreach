import type { PropsWithChildren } from 'react'

import { useEmailBuilderController } from '../hooks/useEmailBuilderController'
import { BuilderContext } from './builderContext'

export function BuilderProvider({ children }: PropsWithChildren) {
  const controller = useEmailBuilderController()
  return <BuilderContext.Provider value={controller}>{children}</BuilderContext.Provider>
}
