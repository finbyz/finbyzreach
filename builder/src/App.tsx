import { lazy, Suspense } from 'react'
import { closestCenter, DndContext, DragOverlay } from '@dnd-kit/core'

import './App.css'
import { BuilderHeader } from './components/BuilderHeader'
import { BuilderWorkspace } from './components/BuilderWorkspace'
import { DialogLoadingFallback, Spinner } from './components/ui'
import { BuilderProvider } from './contexts/BuilderProvider'
import { useBuilder } from './hooks/useBuilder'
import { getErrorMessage } from './lib/errors'

const BuilderDialogs = lazy(() => import('./components/BuilderDialogs').then((module) => ({ default: module.BuilderDialogs })))

function BuilderApp() {
  const {
    templateName,
    sdk,
    document,
    saveConflict,
    dirty,
    stateBytes,
    modal,
    imagePickerBlock,
    recoveryDraft,
    overwriteConfirmationOpen,
    appClassName,
    setShellElement,
    sensors,
    activeDrag,
    setActiveDrag,
    onDragStart,
    onDragEnd,
  } = useBuilder()

  if (!templateName) {
    return (
      <div className="fatal-state">
        <strong>No Email Template selected</strong>
        <span>Open the builder from an Email Template in Desk.</span>
        <a href="/app/email-template">Back to Email Templates</a>
      </div>
    )
  }

  if (sdk.load.error) {
    return (
      <div className="fatal-state">
        <strong>Could not open the builder</strong>
        <span>{getErrorMessage(sdk.load.error)}</span>
        <button type="button" onClick={() => void sdk.load.mutate()}>Try again</button>
      </div>
    )
  }

  if (!document) return <Spinner label="Opening email builder" />

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragStart={onDragStart} onDragEnd={onDragEnd} onDragCancel={() => setActiveDrag(null)}>
      <div ref={setShellElement} className={appClassName}>
        <BuilderHeader />
        <BuilderWorkspace />

        <footer className="builder-status">
          <span>{saveConflict ? 'A newer saved version is available — reload before saving' : dirty ? 'Changes are stored in this browser until saved' : 'Ready'}</span>
          <span><strong>{Math.max(1, Math.round(stateBytes / 1024))} KB</strong> builder state</span>
        </footer>
      </div>

      <DragOverlay dropAnimation={null}>
        {activeDrag && (
          <div className="drag-overlay">
            <span>{activeDrag.kind.includes('section') ? 'Row' : 'Module'}</span>
            <strong>{activeDrag.label}</strong>
          </div>
        )}
      </DragOverlay>

      {(modal || imagePickerBlock || recoveryDraft || overwriteConfirmationOpen) && (
        <Suspense fallback={<DialogLoadingFallback label="Loading dialog" />}>
          <BuilderDialogs />
        </Suspense>
      )}
    </DndContext>
  )
}

function App() {
  return (
    <BuilderProvider>                                                                         
      <BuilderApp />
    </BuilderProvider>
  )
}

export default App
