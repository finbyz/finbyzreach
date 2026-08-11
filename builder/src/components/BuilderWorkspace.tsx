import { lazy, memo, Suspense, useCallback, useState } from 'react'
import { Menu, Monitor, PanelRight, Smartphone } from 'lucide-react'

import { Canvas } from './Canvas'
import { useBuilder } from '../hooks/useBuilder'
import { PanelSkeleton } from './ui'

const Sidebar = lazy(() => import('./Sidebar').then((module) => ({ default: module.Sidebar })))
const Inspector = lazy(() => import('./Inspector').then((module) => ({ default: module.Inspector })))

export const BuilderWorkspace = memo(function BuilderWorkspace() {
  const [referenceDoctypeFocusRequest, setReferenceDoctypeFocusRequest] = useState(0)
  const {
    document,
    isReadOnly,
    readOnlyReason,
    requestVisualEditing,
    selection,
    sidebarOpen,
    inspectorOpen,
    sidebarTab,
    inspectorTab,
    components,
    viewport,
    showStructure,
    pendingImageBlock,
    uploadProgress,
    mergeFields,
    sdk,
    setSidebarTab,
    setInspectorTab,
    addSidebarBlock,
    addSidebarSection,
    select,
    deleteNode,
    insertSavedComponent,
    closePanels,
    toggleSidebar,
    toggleInspector,
    toggleStructure,
    showDesktopViewport,
    showMobileViewport,
    requestAddBlock,
    addDefaultSection,
    updateContent,
    changeColumnWidths,
    editSection,
    openAiSectionRewrite,
    aiEnabled,
    duplicateNode,
    requestSaveComponent,
    chooseImage,
    openTemplateInspector,
    registerTextEditor,
    closeInspector,
    updateMetadata,
    updateSetting,
    updateNode,
    changeLayout,
    uploadInspectorImage,
    retryMergeFields,
    focusTextEditor,
    prepareMergeField,
    insertMergeField,
  } = useBuilder()

  const configurePersonalization = useCallback(() => {
    setReferenceDoctypeFocusRequest((current) => current + 1)
    openTemplateInspector()
  }, [openTemplateInspector])
  const clearReferenceDoctypeFocusRequest = useCallback(() => setReferenceDoctypeFocusRequest(0), [])

  if (!document) return null

  return (
    <div className="builder-workspace">
      {sidebarOpen && (
        <Suspense fallback={<PanelSkeleton side="sidebar" open={sidebarOpen} />}>
          <Sidebar
            open={sidebarOpen}
            schema={document.schema}
            selection={selection}
            components={components}
            activeTab={sidebarTab}
            onTab={setSidebarTab}
            onAddBlock={addSidebarBlock}
            onAddSection={addSidebarSection}
            onSelect={select}
            onDelete={deleteNode}
            onInsertComponent={insertSavedComponent}
            onClose={closePanels}
            readOnly={isReadOnly}
          />
        </Suspense>
      )}
      <button type="button" className="panel-scrim" aria-label="Close open panel" onClick={closePanels} />
      <main className="builder-main">
        <div className="canvas-toolbar">
          <div>
            <button type="button" className={`icon-button panel-toggle${sidebarOpen ? ' is-active' : ''}`} onClick={toggleSidebar} title="Toggle content library"><Menu size={17} /></button>
            <strong>Canvas</strong>
            <span>Click content to edit directly</span>
          </div>
          <div>
            <button type="button" className={`button button--compact${showStructure ? ' is-active' : ''}`} onClick={toggleStructure} title="Toggle structure labels" aria-label="Toggle structure labels">Structure</button>
            <span className="viewport-switch">
              <button type="button" className={viewport === 'desktop' ? 'is-active' : ''} onClick={showDesktopViewport}><Monitor size={15} /><span>Desktop</span></button>
              <button type="button" className={viewport === 'mobile' ? 'is-active' : ''} onClick={showMobileViewport}><Smartphone size={15} /><span>Mobile</span></button>
            </span>
            <button type="button" className={`icon-button panel-toggle${inspectorOpen ? ' is-active' : ''}`} onClick={toggleInspector} title="Toggle inspector"><PanelRight size={17} /></button>
          </div>
        </div>
        {isReadOnly && <div className="read-only-banner" role="status"><strong>{readOnlyReason === 'conflict' ? 'Editing locked' : 'Raw HTML protected'}</strong><span>{readOnlyReason === 'conflict' ? 'A newer saved version is available. Reload latest before editing.' : 'This template is Raw HTML. Visual editing is read-only until you explicitly unlock it.'}</span>{readOnlyReason === 'raw-html' && <button type="button" className="button button--secondary" onClick={requestVisualEditing}>Edit visually</button>}</div>}
        <div className="builder-canvas">
          <Canvas
            schema={document.schema}
            metadata={document.metadata}
            selection={selection}
            viewport={viewport}
            showStructure={showStructure}
            onSelect={select}
            onAddBlock={requestAddBlock}
            onAddSection={addDefaultSection}
            onUpdateContent={updateContent}
            onUpdateNode={updateNode}
            onResizeColumns={changeColumnWidths}
            onEditSection={editSection}
            onAiRewriteSection={openAiSectionRewrite}
            aiEnabled={aiEnabled}
            onDuplicate={duplicateNode}
            onDelete={deleteNode}
            onSaveComponent={requestSaveComponent}
            onPickImage={chooseImage}
            onEditTemplate={openTemplateInspector}
            onTextEditorController={registerTextEditor}
            readOnly={isReadOnly}
          />
        </div>
      </main>
      {inspectorOpen && (
        <Suspense fallback={<PanelSkeleton side="inspector" open={inspectorOpen} />}>
          <Inspector
            open={inspectorOpen}
            document={document}
            selection={selection}
            tab={inspectorTab}
            uploading={sdk.fileUpload.loading && Boolean(pendingImageBlock)}
            uploadProgress={uploadProgress}
            mergeFields={mergeFields}
            mergeFieldsLoading={sdk.mergeFields.isLoading}
            mergeFieldsError={sdk.mergeFields.error}
            onTab={setInspectorTab}
            onClose={closeInspector}
            onMetadata={updateMetadata}
            onSetting={updateSetting}
            onNode={updateNode}
            onLayout={changeLayout}
            onColumnWidths={changeColumnWidths}
            onUploadImage={uploadInspectorImage}
            onChooseImage={chooseImage}
            onConfigurePersonalization={configurePersonalization}
            referenceDoctypeFocusRequest={referenceDoctypeFocusRequest}
            onReferenceDoctypeFocused={clearReferenceDoctypeFocusRequest}
            onRetryMergeFields={retryMergeFields}
            onFocusText={focusTextEditor}
            onPrepareMergeField={prepareMergeField}
            onInsertMergeField={insertMergeField}
            onDuplicate={duplicateNode}
            onDelete={deleteNode}
            onAiRewriteSection={openAiSectionRewrite}
            aiEnabled={aiEnabled}
            readOnly={isReadOnly}
          />
        </Suspense>
      )}
    </div>
  )
})
