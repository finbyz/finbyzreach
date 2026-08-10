import { createContext } from 'react'

import type { useEmailBuilderController } from '../hooks/useEmailBuilderController'

export type EmailBuilderController = ReturnType<typeof useEmailBuilderController>

export const BuilderContext = createContext<EmailBuilderController | null>(null)
