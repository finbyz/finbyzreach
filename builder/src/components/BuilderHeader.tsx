import { memo, useState } from 'react'
import { AlertTriangle, ArrowLeft, Eye, HelpCircle, History, Redo2, Save, Send, Sparkles, ToggleLeft, ToggleRight, Undo2, UsersRound, Wifi, WifiOff } from 'lucide-react'

import { useBuilder } from '../hooks/useBuilder'
import { AiTemplateCreator } from './AiTemplateCreator'

export const BuilderHeader = memo(function BuilderHeader() {
  const {
    templateName,
    templateDoctype,
    mode,
    isReadOnly,
    dirty,
    saving,
    saveConflict,
    canUndo,
    canRedo,
    undo,
    redo,
    openHistory,
    openShortcuts,
    openSuggestions,
    retryPreview,
    openTestDialog,
    saveTemplate,
    autosaveEnabled,
    toggleAutosave,
    sdk,
    realtime,
    suggestions,
    aiEnabled,
    openAiRewrite,
  } = useBuilder()

  const saveStateLabel = saving
    ? 'Saving…'
    : saveConflict
      ? 'Newer version available'
      : dirty
        ? 'Unsaved changes'
        : 'All changes saved'

  const realtimeLabel = realtime.status === 'connected' ? 'Realtime connected' : realtime.status === 'reconnecting' ? 'Realtime reconnecting' : realtime.status === 'disabled' ? 'Realtime disabled' : 'Realtime offline'
  const viewerCount = realtime.viewers.length
  const blockingSuggestions = suggestions.filter((suggestion) => suggestion.severity === 'error').length
  const suggestionCount = suggestions.length

  const [showNewModal, setShowNewModal] = useState(false)
  const isMaster = templateDoctype === 'Email Template Master'
  const formRoute = isMaster ? 'email-template-master' : 'email-template'

  return (
    <>
      <header className="builder-header">
        <div className="builder-title">
          <a className="icon-button builder-back-button" href={`/app/${formRoute}/${encodeURIComponent(templateName)}`} aria-label={`Back to ${templateDoctype}`}><ArrowLeft size={18} /></a>
          <div className="builder-title-copy">
            <small>{isMaster ? 'Master template' : 'Email template'}</small>
            <span className="builder-title-line"><strong>{templateName}</strong><span className="mode-badge">{mode}</span></span>
          </div>
          <button
            type="button"
            className="button button--secondary button--sm button--ai"
            style={{ marginLeft: 8, height: 26, padding: '0 8px', fontSize: 11 }}
            onClick={() => setShowNewModal(true)}
            title="Create a new template with AI from scratch"
          >
            <Sparkles size={12} />
            <span>New</span>
          </button>
        </div>
        <div className="builder-actions" aria-label="Email builder actions">
          <div className="builder-action-cluster builder-action-cluster--status" aria-label="Status">
            <span className={`save-state${dirty ? ' is-dirty' : ''}${saving ? ' is-saving' : ''}${saveConflict ? ' is-conflict' : ''}`} title={saveStateLabel}><i /><span>{saveStateLabel}</span></span>
            <span className={`realtime-state is-${realtime.status}`} title={realtimeLabel}>{realtime.connected ? <Wifi size={13} /> : <WifiOff size={13} />}<span>Socket</span></span>
            {viewerCount > 0 && <span className="viewer-state" title={realtime.viewers.join(', ')}><UsersRound size={13} /><span>{viewerCount} viewing</span></span>}
          </div>
          <div className="builder-action-cluster builder-action-cluster--edit" aria-label="Edit controls">
            <span className="button-group">
              <button type="button" className="icon-button" onClick={undo} disabled={isReadOnly || !canUndo} title="Undo"><Undo2 size={16} /></button>
              <button type="button" className="icon-button" onClick={redo} disabled={isReadOnly || !canRedo} title="Redo"><Redo2 size={16} /></button>
            </span>
            <button type="button" className={`button button--secondary autosave-toggle${autosaveEnabled ? ' is-active' : ''}`} data-action="autosave" onClick={toggleAutosave} disabled={isReadOnly} title={autosaveEnabled ? 'Autosave is on' : 'Autosave is off'} aria-label={autosaveEnabled ? 'Turn autosave off' : 'Turn autosave on'} aria-pressed={autosaveEnabled}>{autosaveEnabled ? <ToggleRight size={15} /> : <ToggleLeft size={15} />}<span>Autosave {autosaveEnabled ? 'on' : 'off'}</span></button>
          </div>
          <div className="builder-action-cluster builder-action-cluster--support" aria-label="Review tools">
            <button type="button" className="button button--secondary button--utility" data-action="shortcuts" onClick={openShortcuts} title="Keyboard shortcuts" aria-label="Keyboard shortcuts"><HelpCircle size={15} /><span>Shortcuts</span></button>
            <button type="button" className={`button button--secondary button--utility suggestions-button${suggestionCount ? ' has-suggestions' : ''}${blockingSuggestions ? ' has-errors' : ''}`} data-action="suggestions" onClick={openSuggestions} title={suggestionCount ? `${suggestionCount} builder suggestion${suggestionCount === 1 ? '' : 's'}` : 'No builder suggestions'} aria-label="Builder suggestions"><AlertTriangle size={15} /><span>Suggestions</span>{suggestionCount > 0 && <strong>{suggestionCount}</strong>}</button>
            <button type="button" className="button button--secondary button--utility" data-action="history" onClick={openHistory} title="Revision history" aria-label="Revision history"><History size={15} /><span>History</span></button>
          </div>
          <div className="builder-action-cluster builder-action-cluster--primary" aria-label="Send and save">
            {aiEnabled && <button type="button" className="button button--secondary button--ai" data-action="ai-rewrite" onClick={openAiRewrite} disabled={isReadOnly} title="Rewrite this email with AI" aria-label="AI rewrite"><Sparkles size={15} /><span>AI Rewrite</span></button>}
            <button type="button" className="button button--secondary" data-action="preview" onClick={retryPreview} disabled={sdk.preview.loading} title="Preview" aria-label="Preview"><Eye size={15} /><span>Preview</span></button>
            <button type="button" className="button button--secondary" data-action="test" onClick={openTestDialog} title="Send test email" aria-label="Send test email"><Send size={15} /><span>Test email</span></button>
            <button type="button" className="button button--primary" data-action="save" onClick={saveTemplate} disabled={isReadOnly || saving || !dirty} title="Save template" aria-label="Save template"><Save size={15} /><span>{saving ? 'Saving' : 'Save'}</span></button>
          </div>
        </div>
      </header>
      {showNewModal && <AiTemplateCreator mode="modal" templateDoctype={templateDoctype} onClose={() => setShowNewModal(false)} />}
    </>
  )
})
