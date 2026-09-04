import { memo, useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { AlertTriangle, CheckCircle2, Clock3, Eye, FileCode2, ImagePlus, MoreVertical, Monitor, RefreshCw, Reply, RotateCcw, Search, Smartphone, Sparkles, Star, Trash2, Upload, User, Wand2, Save } from 'lucide-react'

import { useBuilder } from '../hooks/useBuilder'
import { getErrorMessage } from '../lib/errors'
import type { BuilderDocument, BuilderImageFile, RevisionSummary, Viewport } from '../types'
import type { BuilderSuggestion } from '../lib/suggestions'
import { Modal, SkeletonLine, Spinner } from './ui'

export type ModalName = 'preview' | 'revision-preview' | 'test' | 'history' | 'save-component' | 'conflict' | 'shortcuts' | 'suggestions' | 'visual-unlock' | 'reference-doctype-change' | 'ai' | null
export type PreviewFormat = 'html' | 'plain'
export type RecoveryDraft = { document: BuilderDocument }

const COMPONENT_CATEGORIES = ['Header', 'Content', 'CTA', 'Footer', 'Social', 'Other']

const SHORTCUT_GROUPS = [
  { title: 'Editing', items: [['Ctrl / ⌘ + Z', 'Undo last change'], ['Ctrl / ⌘ + Shift + Z', 'Redo last undo'], ['Ctrl / ⌘ + Y', 'Redo last undo'], ['Delete / Backspace', 'Delete selected row or block']] },
  { title: 'Canvas tips', items: [['Click content', 'Select and edit directly'], ['Drag handle', 'Move rows or blocks'], ['Add content', 'Insert into the selected column']] },
  { title: 'Text editing', items: [['Enter', 'New compact line'], ['Ctrl / ⌘ + B', 'Bold selected text'], ['Ctrl / ⌘ + I', 'Italic selected text'], ['Ctrl / ⌘ + U', 'Underline selected text']] },
]

function stripUnsafePreviewScripts(html: string) {
  return html
    .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
    .replace(/\s+on[a-z]+=("[^"]*"|'[^']*'|[^\s>]+)/gi, '')
}


function withPreviewFitStyles(html: string) {
  const safeHtml = stripUnsafePreviewScripts(html)
  const previewStyles = [
    '<style id="etb-preview-fit">',
    'html,body{height:auto!important;min-height:0!important;overflow:hidden!important;background:transparent!important;}',
    'body{display:block!important;margin:0!important;padding:0!important;}',
    'body>table[role="presentation"]{height:auto!important;min-height:0!important;background:transparent!important;}',
    'table.etb-content{height:auto!important;min-height:0!important;}',
    '</style>',
  ].join('')
  return safeHtml.includes('</head>') ? safeHtml.replace('</head>', `${previewStyles}</head>`) : previewStyles + safeHtml
}


type RevisionTime = Pick<RevisionSummary, 'creation' | 'creation_epoch' | 'timezone'>

function revisionDate(value: RevisionTime) {
  const date = value.creation_epoch ? new Date(value.creation_epoch) : new Date(value.creation)
  return Number.isNaN(date.getTime()) ? null : date
}

function formatRevisionTime(value: RevisionTime) {
  const date = revisionDate(value)
  if (!date) return value.creation || 'Unknown time'
  try {
    return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short', timeZone: value.timezone || undefined, timeZoneName: value.timezone ? 'short' : undefined }).format(date)
  } catch {
    return date.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })
  }
}

function relativeRevisionTime(value: RevisionTime) {
  const date = revisionDate(value)
  if (!date) return ''
  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000))
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`
  return formatRevisionTime(value)
}

function formatBytes(bytes?: number) {
  if (!bytes) return '—'
  if (bytes < 1024) return `${bytes} B`
  return `${Math.max(1, Math.round(bytes / 1024))} KB`
}

function formatImageSize(bytes?: number) {
  if (!bytes) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function groupSuggestions(suggestions: BuilderSuggestion[]) {
  return suggestions.reduce<Record<string, BuilderSuggestion[]>>((groups, suggestion) => {
    const key = suggestion.category
    groups[key] = groups[key] || []
    groups[key].push(suggestion)
    return groups
  }, {})
}

function suggestionSeverityLabel(severity: BuilderSuggestion['severity']) {
  if (severity === 'error') return 'Needs fix'
  if (severity === 'warning') return 'Suggestion'
  return 'Tip'
}

function ImagePickerDialog() {
  const {
    imagePickerBlock,
    imagePickerScope,
    imageSearch,
    imageLibrary,
    imageLibraryLoading,
    imageLibraryLoadingMore,
    imageLibraryHasMore,
    imageLibraryError,
    pendingImageBlock,
    uploadProgress,
    optimizeImages,
    maxImageWidth,
    setOptimizeImages,
    setMaxImageWidth,
    closeImagePicker,
    changeImageScope,
    changeImageSearch,
    refreshImageLibrary,
    loadMoreImages,
    selectExistingImage,
    uploadImageFromPicker,
  } = useBuilder()

  const [activeTab, setActiveTab] = useState<'upload' | 'library'>('upload')
  if (!imagePickerBlock) return null
  const uploading = pendingImageBlock === imagePickerBlock
  const onFile = (file?: File) => { if (file) uploadImageFromPicker(file) }
  return <Modal title="Choose image" onClose={closeImagePicker} width={800}>
    <div className="image-picker">
      <nav className="image-picker-tabs" aria-label="Image source">
        <button type="button" className={activeTab === 'upload' ? 'is-active' : ''} onClick={() => setActiveTab('upload')}><Upload size={15} /> Upload new</button>
        <button type="button" className={activeTab === 'library' ? 'is-active' : ''} onClick={() => { setActiveTab('library'); void refreshImageLibrary(imagePickerScope, imageSearch) }}><ImagePlus size={15} /> Choose existing</button>
      </nav>
      {activeTab === 'upload' ? <div className="image-upload-panel">
        <label className={`image-upload-drop${uploading ? ' is-uploading' : ''}`}>
          <Upload size={28} />
          <strong>{uploading ? 'Uploading image…' : 'Upload a public email image'}</strong>
          <span>PNG, JPG, WebP, or GIF up to 10 MB. Recipients can only see public files.</span>
          {uploading && <div className="image-upload-progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={uploadProgress}><span className="image-upload-progress-track"><i style={{ width: `${uploadProgress}%` }} /></span><small>{uploadProgress}%</small></div>}
          <input type="file" accept="image/*" disabled={uploading} onChange={(event) => { onFile(event.target.files?.[0]); event.target.value = '' }} />
        </label>
        <div className={`image-optimization-card${optimizeImages ? '' : ' is-disabled'}`}>
          <label className="toggle-field"><span>Optimize upload with Frappe</span><input type="checkbox" checked={optimizeImages} onChange={(event) => setOptimizeImages(event.target.checked)} /><i /></label>
          <p>Compress large JPG/PNG/WebP files during upload. GIF and SVG stay unchanged.</p>
          <div className="image-resize-mode" aria-label="Image resize mode">
            <button type="button" className={maxImageWidth === 'auto' ? 'is-active' : ''} disabled={!optimizeImages} onClick={() => setMaxImageWidth('auto')}>Auto</button>
            <button type="button" className={maxImageWidth !== 'auto' ? 'is-active' : ''} disabled={!optimizeImages} onClick={() => setMaxImageWidth(maxImageWidth === 'auto' ? 1600 : maxImageWidth)}>Resize</button>
          </div>
          <label className="image-max-width"><span>Max width</span><input type="number" min={320} max={2400} value={maxImageWidth === 'auto' ? '' : maxImageWidth} disabled={!optimizeImages || maxImageWidth === 'auto'} placeholder="Auto" onChange={(event) => setMaxImageWidth(Number(event.target.value) || 1600)} /><small>{maxImageWidth === 'auto' ? 'auto' : 'px'}</small></label>
          <small className="image-optimize-note">Auto keeps the original dimensions and lets Frappe optimize safely. Resize caps very large images for lighter emails.</small>
        </div>
      </div> : <div className="image-library-panel">
        <div className="image-library-toolbar">
          <span className="segmented-control">
            <button type="button" className={imagePickerScope === 'template' ? 'is-active' : ''} onClick={() => changeImageScope('template')}>This template</button>
            <button type="button" className={imagePickerScope === 'public' ? 'is-active' : ''} onClick={() => changeImageScope('public')}>Public library</button>
          </span>
          <label className="image-library-search"><Search size={14} /><input value={imageSearch} placeholder="Search images" onChange={(event) => changeImageSearch(event.target.value)} /></label>
          <button type="button" className="icon-button" aria-label="Refresh image library" onClick={() => void refreshImageLibrary(imagePickerScope, imageSearch)}><RefreshCw size={15} /></button>
        </div>
        {Boolean(imageLibraryError) && <div className="image-library-message is-error">{getErrorMessage(imageLibraryError, 'Could not load images.')}</div>}
        {imageLibraryLoading && !imageLibrary.length ? <div className="image-library-grid is-loading">{Array.from({ length: 8 }).map((_, index) => <div className="image-card is-skeleton" key={index}><SkeletonLine height={92} /><SkeletonLine width="70%" height={10} /></div>)}</div> : imageLibrary.length ? <>
          <div className="image-library-grid">
            {imageLibrary.map((file: BuilderImageFile) => <button type="button" className="image-card" key={file.name} disabled={uploading} onClick={() => selectExistingImage(file.name)}>
              <span className="image-card-thumb"><img src={file.thumbnail_url || file.file_url} alt="" loading="lazy" /></span>
              <strong title={file.file_name}>{file.file_name}</strong>
              <small>{file.is_attached_to_template ? 'Attached here' : 'Public file'}{file.file_size ? ` · ${formatImageSize(file.file_size)}` : ''}</small>
            </button>)}
          </div>
          <div className="image-library-footer">
            <span>{imageLibrary.length} image{imageLibrary.length === 1 ? '' : 's'} loaded</span>
            {imageLibraryHasMore ? <button type="button" className="button button--secondary" disabled={imageLibraryLoadingMore || uploading} onClick={loadMoreImages}>{imageLibraryLoadingMore ? 'Loading…' : 'Load more'}</button> : <small>End of library</small>}
          </div>
        </> : <div className="image-library-empty"><ImagePlus size={28} /><strong>No public images found</strong><span>{imagePickerScope === 'template' ? 'Upload an image first, or switch to the public library.' : 'Try a different search term.'}</span></div>}
      </div>}
    </div>
  </Modal>
}

function RevisionCard({ revision, latest, onPreview, onRestore }: { revision: RevisionSummary; latest: boolean; onPreview: (name: string) => void; onRestore: (name: string) => void }) {
  return (
    <article className={'revision-card' + (latest ? ' is-latest' : '')}>
      <div className="revision-card__main">
        <header>
          <span className="revision-card__number">Revision {revision.revision_number}</span>
          {latest && <span className="revision-badge">Latest saved</span>}
        </header>
        <strong>{revision.subject || 'No subject'}</strong>
        <p>{revision.preheader || 'No preview text'}</p>
        {revision.save_note && <em>{revision.save_note}</em>}
      </div>
      <div className="revision-card__meta">
        <span className="revision-card__time" title={formatRevisionTime(revision)}><Clock3 size={13} /><i>{relativeRevisionTime(revision)}</i><small>{formatRevisionTime(revision)}</small></span>
        <span><FileCode2 size={13} /> {formatBytes(revision.html_bytes)}</span>
        {revision.content_hash && <code>{revision.content_hash}</code>}
      </div>
      <div className="revision-card__actions">
        <button type="button" className="button button--secondary" onClick={() => onPreview(revision.name)}><Eye size={14} /> Preview</button>
        <button type="button" className="button button--secondary revision-restore" onClick={() => onRestore(revision.name)}><RotateCcw size={14} /> Restore</button>
      </div>
    </article>
  )
}

function PreviewLoadingSkeleton({ device, label }: { device: Viewport; label: string }) {
  return (
    <div className={'preview-frame is-' + device} role="status" aria-live="polite" aria-label={label}>
      <div className={'gmail-preview-shell is-' + device}>
        <div className="gmail-preview-clientbar">
          <span className="gmail-preview-dot is-red" />
          <span className="gmail-preview-dot is-yellow" />
          <span className="gmail-preview-dot is-green" />
          <SkeletonLine width="96px" height={10} />
        </div>
        <article className="gmail-message preview-loading-card">
          <header className="gmail-message__subject"><SkeletonLine width="48%" height={20} /></header>
          <div className="gmail-message__meta">
            <SkeletonLine width="36px" height={36} />
            <div className="preview-loading-stack">
              <SkeletonLine width="180px" height={12} />
              <SkeletonLine width="120px" height={9} />
            </div>
            <SkeletonLine width="68px" height={10} />
          </div>
          <div className="gmail-message__body preview-loading-body">
            <div className="preview-loading-email">
              <SkeletonLine width="72%" height={18} />
              <SkeletonLine width="100%" height={14} />
              <SkeletonLine width="94%" height={14} />
              <SkeletonLine width="45%" height={34} />
              <SkeletonLine width="100%" height={150} />
            </div>
          </div>
        </article>
      </div>
    </div>
  )
}

const PreviewMailChrome = memo(function PreviewMailChrome({ subject, preheader, device, children }: { subject: string; preheader?: string; device: Viewport; children: ReactNode }) {
  const previewTime = useMemo(() => new Date().toLocaleString([], { hour: 'numeric', minute: '2-digit' }), [])

  return (
    <div className={'gmail-preview-shell is-' + device}>
      <div className="gmail-preview-clientbar">
        <span className="gmail-preview-dot is-red" />
        <span className="gmail-preview-dot is-yellow" />
        <span className="gmail-preview-dot is-green" />
        <strong>Inbox preview</strong>
      </div>
      <article className="gmail-message">
        <header className="gmail-message__subject">{subject || '(No subject)'}</header>
        <div className="gmail-message__meta">
          <span className="gmail-avatar">ET</span>
          <div className="gmail-sender">
            <strong>Email Template Preview</strong>
            <span>&lt;preview@example.com&gt;</span>
            <small>to me</small>
          </div>
          <div className="gmail-actions">
            <span>{previewTime}</span>
            <button type="button" aria-label="Star preview"><Star size={15} /></button>
            <button type="button" aria-label="Reply preview"><Reply size={15} /></button>
            <button type="button" aria-label="More preview actions"><MoreVertical size={15} /></button>
          </div>
        </div>
        {preheader && <p className="gmail-message__preheader">{preheader}</p>}
        <div className="gmail-message__body">{children}</div>
      </article>
    </div>
  )
})

const CompiledPreviewFrame = memo(function CompiledPreviewFrame({ html, device }: { html: string; device: Viewport }) {
  const frameRef = useRef<HTMLIFrameElement>(null)
  const boundDocumentRef = useRef<Document | null>(null)
  const resizeObserverRef = useRef<ResizeObserver | null>(null)
  const measureTimersRef = useRef<number[]>([])
  const [height, setHeight] = useState(650)
  const [loaded, setLoaded] = useState(false)

  const clearMeasureTimers = useCallback(() => {
    measureTimersRef.current.forEach((timer) => window.clearTimeout(timer))
    measureTimersRef.current = []
  }, [])

  const measure = useCallback(() => {
    try {
      const frameDocument = frameRef.current?.contentDocument
      if (!frameDocument) return
      if (boundDocumentRef.current !== frameDocument) {
        resizeObserverRef.current?.disconnect()
        frameDocument.addEventListener('click', (event) => {
          if ((event.target as Element | null)?.closest('a')) event.preventDefault()
        })
        frameDocument.querySelectorAll('img').forEach((image) => {
          if (!image.complete) {
            image.addEventListener('load', () => requestAnimationFrame(measure), { once: true })
            image.addEventListener('error', () => requestAnimationFrame(measure), { once: true })
          }
        })
        if ('ResizeObserver' in window && frameDocument.body) {
          resizeObserverRef.current = new ResizeObserver(() => requestAnimationFrame(measure))
          resizeObserverRef.current.observe(frameDocument.body)
        }
        boundDocumentRef.current = frameDocument
      }
      const body = frameDocument.body
      const documentElement = frameDocument.documentElement
      const emailContent = frameDocument.querySelector('table.etb-content') as HTMLElement | null
      const contentRoot = emailContent || (body?.firstElementChild as HTMLElement | null)
      if (!contentRoot) return
      const rootRect = contentRoot.getBoundingClientRect()
      const rootTop = rootRect.top || 0
      let contentBottom = rootRect.top
      contentRoot.querySelectorAll('img,table,td,div,p,h1,h2,h3,a,span,hr').forEach((element) => {
        if (element === contentRoot) return
        const rect = (element as HTMLElement).getBoundingClientRect()
        const visibleElement = rect.width > 0 || rect.height > 0
        if (visibleElement) contentBottom = Math.max(contentBottom, rect.bottom)
      })
      if (contentBottom <= rootRect.top) contentBottom = rootRect.bottom
      const measuredContentHeight = Math.max(
        contentBottom - rootTop,
        contentRoot.scrollHeight || 0,
        body?.scrollHeight || 0,
        documentElement?.scrollHeight || 0,
      )
      setHeight(Math.max(80, Math.min(3200, Math.ceil(measuredContentHeight) + 2)))
      setLoaded(true)
    } catch {
      setHeight(device === 'mobile' ? 560 : 650)
      setLoaded(true)
    }
  }, [device])

  useEffect(() => {
    boundDocumentRef.current = null
    resizeObserverRef.current?.disconnect()
    resizeObserverRef.current = null
    clearMeasureTimers()
    setLoaded(false)
    setHeight(device === 'mobile' ? 560 : 650)
    const checkpoints = [0, 80, 180, 360, 700, 1200]
    measureTimersRef.current = checkpoints.map((delay) => window.setTimeout(() => requestAnimationFrame(measure), delay))
    const fallback = window.setTimeout(() => setLoaded(true), 1300)
    return () => {
      window.clearTimeout(fallback)
      clearMeasureTimers()
      resizeObserverRef.current?.disconnect()
      resizeObserverRef.current = null
    }
  }, [clearMeasureTimers, device, html, measure])

  const previewHtml = useMemo(() => withPreviewFitStyles(html), [html])
  const frameWidth = device === 'mobile' ? 375 : 900

  return (
    <div className={'compiled-preview-frame' + (loaded ? ' is-loaded' : ' is-loading')} style={{ width: frameWidth, maxWidth: '100%' }}>
      {!loaded && (
        <div className="compiled-preview-skeleton" style={{ height }}>
          <SkeletonLine width="66%" height={18} />
          <SkeletonLine width="100%" height={14} />
          <SkeletonLine width="88%" height={14} />
          <SkeletonLine width="34%" height={38} />
          <SkeletonLine width="100%" height={Math.max(130, Math.min(260, height - 150))} />
        </div>
      )}
      <iframe
        key={`${device}:${previewHtml.length}`}
        ref={frameRef}
        sandbox="allow-same-origin"
        referrerPolicy="no-referrer"
        title={device === 'mobile' ? 'Mobile compiled email preview' : 'Desktop compiled email preview'}
        srcDoc={previewHtml}
        onLoad={() => { measure(); requestAnimationFrame(measure) }}
        style={{ width: frameWidth, height }}
      />
    </div>
  )
})

// Fallback chips only, used when the Email Builder AI Prompt doctype has none.
const AI_PROMPT_FALLBACK = [
  { title: 'More professional', prompt: 'Make the tone more professional and concise' },
  { title: 'Stronger CTA', prompt: 'Strengthen the call to action and make the button stand out' },
  { title: 'Shorten it', prompt: 'Shorten the copy and add a clear headline' },
]

function AiThinkingIndicator({ label }: { label?: string | null }) {
  return (
    <div className="ai-chat-bubble ai-chat-bubble--assistant ai-chat-bubble--thinking">
      <div className="ai-chat-bubble__avatar">
        <Sparkles size={14} />
      </div>
      <div className="ai-chat-bubble__content">
        <div className="ai-thinking-indicator" role="status" aria-live="polite">
          <div className="ai-thinking-dots">
            <span />
            <span />
            <span />
          </div>
          <span className="ai-thinking-text">{label || 'Generating response...'}</span>
        </div>
      </div>
    </div>
  )
}

function AiRewriteDialog() {
  const {
    document,
    aiPrompt,
    aiProposal,
    aiGenerating,
    aiLiveStep,
    aiScope,
    aiSamplePrompts,
    chatTurns,
    setAiPrompt,
    closeAiRewrite,
    generateAiRewrite,
    acceptAiProposal,
    discardAiProposal,
    applyPastProposal,
    loadProposalPreview,
    clearAiProposal,
    clearAiChat,
    saveAiSamplePrompt,
  } = useBuilder()

  const chatContainerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight
    }
  }, [chatTurns, aiGenerating, aiProposal])

  const sectionMode = aiScope?.type === 'section'
  const title = sectionMode ? 'AI Row Copilot' : 'AI Copilot'
  const chips = aiSamplePrompts.length ? aiSamplePrompts : AI_PROMPT_FALLBACK
  const accent = document?.schema.settings.button_background || document?.schema.settings.link_color || ''
  const accentStyle = accent ? ({ ['--ai-accent']: accent } as CSSProperties) : undefined

  // Active proposal is set when a rewrite is generated OR when viewing a past turn
  const activeProposal = aiProposal

  const isHistorical = Boolean(
    activeProposal &&
      (activeProposal.status === 'accepted' ||
        activeProposal.status === 'rejected' ||
        chatTurns.some(
          (t) =>
            t.proposal?.proposal_id === activeProposal.proposal_id &&
            t.status &&
            t.status !== 'pending'
        ))
  )

  const [selection, setSelection] = useState<{
    text: string
    top: number
    left: number
    showInput: boolean
    title: string
  } | null>(null)

  const handleMouseUp = useCallback((e: React.MouseEvent) => {
    const target = e.target as HTMLElement
    if (target.closest('.ai-selection-popup')) return

    let text = ''
    
    if (target.classList.contains('ai-prompt-input') && target instanceof HTMLTextAreaElement) {
      text = target.value.substring(target.selectionStart || 0, target.selectionEnd || 0).trim()
    } else {
      if (selection && !selection.showInput) setSelection(null)
      return
    }

    if (!text) {
      if (selection && !selection.showInput) setSelection(null)
      return
    }

    setSelection({
      text,
      top: e.clientY,
      left: e.clientX,
      showInput: false,
      title: '',
    })
  }, [selection])

  return (
    <Modal title={title} onClose={closeAiRewrite} width={activeProposal ? 1200 : 720}>
      <div className="ai-dialog" style={accentStyle} onMouseUp={handleMouseUp}>
        <div className={`ai-copilot-container ${activeProposal ? 'has-proposal' : ''}`}>
          {/* Left Column: Multi-turn Chat Thread */}
          <div className="ai-copilot-chat">
            {chatTurns.length > 0 && (
              <div className="ai-chat-header-actions" style={{ display: 'flex', justifyContent: 'flex-end', padding: '0 0 6px 0' }}>
                <button type="button" className="button button--tertiary button--sm" onClick={clearAiChat} title="Clear conversation history" style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', fontSize: '12px' }}>
                  <Trash2 size={13} />
                  <span>Clear history</span>
                </button>
              </div>
            )}
            <div className="ai-chat-thread" ref={chatContainerRef}>
              {chatTurns.length === 0 && (
                <div className="ai-chat-welcome">
                  <p className="ai-lead">
                    {sectionMode
                      ? 'Ask the AI Copilot to rewrite this selected row. Describe your vision, paste a URL, or ask for specific style changes.'
                      : 'Ask the AI Copilot to design or edit your email. You can refine the email over multiple conversation turns.'}
                  </p>
                </div>
              )}
              {chatTurns.map((turn) => {
                const isUser = turn.role === 'user'
                const proposalId = turn.proposal?.proposal_id || (turn.id.startsWith('u-') || turn.id.startsWith('e-') ? null : turn.id)
                const isViewingThis = Boolean(proposalId && activeProposal?.proposal_id === proposalId)
                const uniqueWarnings = turn.proposal?.warnings
                  ? Array.from(new Set(turn.proposal.warnings.map((w) => w.trim()).filter(Boolean)))
                  : []

                return (
                  <div key={turn.id} className={`ai-chat-bubble ai-chat-bubble--${turn.role}${turn.isError ? ' ai-chat-bubble--error' : ''}`}>
                    <div className="ai-chat-bubble__avatar">
                      {isUser ? <User size={14} /> : <Sparkles size={14} />}
                    </div>
                    <div className="ai-chat-bubble__content">
                      <div className="ai-chat-bubble__header">
                        <span className="ai-chat-bubble__author">{isUser ? 'You' : 'AI Copilot'}</span>
                      </div>
                      <p className="ai-chat-bubble__text">{turn.text}</p>
                      {turn.proposal?.change_notes && turn.proposal.change_notes.length > 0 && (
                        <ul className="ai-change-notes">
                          {turn.proposal.change_notes.map((note, index) => (
                            <li key={index}>{note}</li>
                          ))}
                        </ul>
                      )}
                      {uniqueWarnings.length > 0 && (
                        <div className="ai-warnings">
                          {uniqueWarnings.map((warning, index) => (
                            <span key={index} className="ai-warning-tag">
                              <AlertTriangle size={12} />
                              {warning}
                            </span>
                          ))}
                        </div>
                      )}
                      {proposalId && (
                        <div className="ai-turn-actions">
                          {turn.status && turn.status !== 'pending' && (
                            <span className={`ai-proposal-badge is-${turn.status}`}>
                              {turn.status === 'accepted' ? '✓ Accepted' : '✕ Rejected'}
                            </span>
                          )}
                          <button
                            type="button"
                            className={`button--view-changes ${isViewingThis ? 'is-active' : ''}`}
                            onClick={() => loadProposalPreview(proposalId)}
                            title={isViewingThis ? 'Close side preview' : 'View before & after comparison'}
                          >
                            <Eye size={12} />
                            <span>{isViewingThis ? 'Hide Changes' : 'View Changes'}</span>
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
              {aiGenerating && <AiThinkingIndicator label={aiLiveStep} />}
            </div>

            {/* Prompt Input Pane */}
            <div className="ai-chat-input-pane">
              <div className="ai-suggestion-chips">
                {chips.map((chip) => (
                  <button
                    type="button"
                    key={chip.title}
                    className="ai-chip"
                    disabled={aiGenerating}
                    onClick={() => setAiPrompt(chip.prompt)}
                    title={chip.prompt}
                  >
                    {chip.title}
                  </button>
                ))}
              </div>
              <div className="ai-input-row">
                <textarea
                  className="ai-prompt-input"
                  value={aiPrompt}
                  onChange={(event) => setAiPrompt(event.target.value)}
                  placeholder={sectionMode ? 'e.g. Make this row more persuasive or update button color' : 'e.g. Make it more modern or paste a URL...'}
                  rows={2}
                  autoFocus
                  disabled={aiGenerating}
                  onSelect={(e) => {
                    const target = e.target as HTMLTextAreaElement
                    const text = target.value.substring(target.selectionStart || 0, target.selectionEnd || 0).trim()
                    if (text) {
                      const rect = target.getBoundingClientRect()
                      // Only update if no selection or text changed, to preserve mouse coords if possible
                      if (!selection || selection.text !== text) {
                        setSelection({
                          text,
                          top: rect.top,
                          left: rect.left + rect.width / 2,
                          showInput: false,
                          title: '',
                        })
                      }
                    } else if (selection && !selection.showInput) {
                      setSelection(null)
                    }
                  }}
                  onKeyDown={(event) => {
                    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter' && aiPrompt.trim() && !aiGenerating) {
                      generateAiRewrite()
                    }
                  }}
                />
                <button
                  type="button"
                  className="button button--secondary button--ai"
                  onClick={generateAiRewrite}
                  disabled={!aiPrompt.trim() || aiGenerating}
                  title="Send message to AI Copilot"
                >
                  <Wand2 size={15} />
                </button>
              </div>
            </div>
          </div>

          {/* Right Column: Side-by-Side Before/After Visual Preview */}
          {activeProposal && (
            <div className="ai-copilot-preview">
              <div className="ai-before-after">
                <section className="ai-pane">
                  <header>Before</header>
                  {activeProposal.before_html ? (
                    <div className="preview-frame is-desktop">
                      <CompiledPreviewFrame html={activeProposal.before_html} device="desktop" />
                    </div>
                  ) : (
                    <div className="ai-pane-empty">Current design preview unavailable.</div>
                  )}
                </section>
                <section className="ai-pane ai-pane--after">
                  <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span>After · {sectionMode ? 'row proposal' : 'AI proposal'}</span>
                    <button
                      type="button"
                      className="button button--tertiary button--sm"
                      onClick={clearAiProposal}
                      title="Close side preview pane"
                      style={{ padding: '2px 6px', fontSize: '11px', height: 'auto', lineHeight: 1 }}
                    >
                      ✕
                    </button>
                  </header>
                  <div className="preview-frame is-desktop">
                    <CompiledPreviewFrame html={activeProposal.preview_html} device="desktop" />
                  </div>
                </section>
              </div>
              <div className="ai-proposal-actions">
                {isHistorical ? (
                  <>
                    <button type="button" className="button button--secondary" onClick={clearAiProposal}>
                      Close Preview
                    </button>
                    <button
                      type="button"
                      className="button button--primary"
                      onClick={() => activeProposal && applyPastProposal(activeProposal)}
                      disabled={!document || !activeProposal.schema}
                    >
                      <RotateCcw size={15} /> Apply This Version
                    </button>
                  </>
                ) : (
                  <>
                    <button type="button" className="button button--secondary" onClick={discardAiProposal}>
                      Discard
                    </button>
                    <button type="button" className="button button--secondary" onClick={generateAiRewrite} disabled={aiGenerating}>
                      <RefreshCw size={15} /> Regenerate
                    </button>
                    <button type="button" className="button button--primary" onClick={acceptAiProposal} disabled={!document}>
                      <CheckCircle2 size={15} /> {sectionMode ? 'Accept Row' : 'Accept Changes'}
                    </button>
                  </>
                )}
              </div>
            </div>
          )}
        </div>
        
        {selection && (
          <div 
            className="ai-selection-popup"
            style={{ position: 'fixed', top: selection.top - 45, left: selection.left, transform: 'translateX(-50%)', zIndex: 99999 }}
            onMouseUp={(e) => e.stopPropagation()}
          >
            {!selection.showInput ? (
              <button 
                type="button" 
                className="button button--primary button--sm" 
                onClick={() => setSelection({ ...selection, showInput: true })}
                title="Save as AI Sample Prompt"
                style={{ padding: '6px', borderRadius: '50%', boxShadow: '0 4px 12px rgba(0,0,0,0.25)' }}
              >
                <Save size={16} />
              </button>
            ) : (
              <div className="ai-selection-input-row" style={{ display: 'flex', gap: '4px', background: 'var(--bg)', padding: '6px', borderRadius: '6px', boxShadow: '0 4px 16px rgba(0,0,0,0.2)', border: '1px solid var(--border)' }}>
                <input 
                  type="text" 
                  autoFocus
                  placeholder="Chip title..." 
                  value={selection.title}
                  onChange={(e) => setSelection({ ...selection, title: e.target.value })}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && selection.title.trim()) {
                      saveAiSamplePrompt(selection.title.trim(), selection.text)
                      setSelection(null)
                      window.getSelection()?.removeAllRanges()
                    } else if (e.key === 'Escape') {
                      setSelection(null)
                    }
                  }}
                  style={{ width: '140px', padding: '4px 8px', fontSize: '13px', border: '1px solid var(--border)', borderRadius: '4px', outline: 'none' }}
                />
                <button 
                  type="button"
                  className="button button--primary button--sm"
                  disabled={!selection.title.trim()}
                  title="Save Chip"
                  onClick={() => {
                    if (selection.title.trim()) {
                      saveAiSamplePrompt(selection.title.trim(), selection.text)
                      setSelection(null)
                      window.getSelection()?.removeAllRanges()
                    }
                  }}
                  style={{ padding: '0 8px' }}
                >
                  <CheckCircle2 size={16} />
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </Modal>
  )
}

export const BuilderDialogs = memo(function BuilderDialogs() {
  const {
    modal,
    document,
    preview,
    previewError,
    revisionPreview,
    revisionPreviewError,
    previewFormat,
    previewWidth,
    uiMode,
    recipient,
    componentName,
    componentCategory,
    revisions,
    suggestions,
    recoveryDraft,
    overwriteConfirmationOpen,
    pendingReferenceDoctypeChange,
    sdk,
    closeModal,
    setPreviewFormat,
    setPreviewWidth,
    setRecipient,
    setComponentName,
    setComponentCategory,
    retryPreview,
    retryRevisionPreview,
    sendTestEmail,
    saveReusableContent,
    retryRevisions,
    restoreRevisionByName,
    previewRevisionByName,
    backToHistory,
    discardRecoveryDraft,
    restoreRecoveryDraft,
    closeOverwriteConfirmation,
    confirmOverwrite,
    confirmVisualEditing,
    reloadLatest,
    cancelReferenceDoctypeChange,
    keepReferenceDependentContent,
    removeReferenceDependentFields,
  } = useBuilder()

  const compactPreview = uiMode === 'mobile'
  const activePreviewWidth = compactPreview ? 'mobile' : previewWidth

  useEffect(() => {
    if (compactPreview && previewWidth !== 'mobile') setPreviewWidth('mobile')
  }, [compactPreview, previewWidth, setPreviewWidth])

  if (!document) return null

  return (
    <>
      <ImagePickerDialog />
      {modal === 'ai' && <AiRewriteDialog />}
      {modal === 'preview' && <Modal title="Compiled email preview" onClose={closeModal} width={1160}>
        <div className="preview-dialog">
          <header className="preview-inbox">
            <span><small>Subject</small><strong>{preview?.subject || document.metadata.subject || '(No subject)'}</strong></span>
            <span><small>Preheader</small><strong>{document.metadata.preheader || 'No preview text'}</strong></span>
            {preview && <span className="preview-size">{Math.max(1, Math.round(preview.bytes / 1024))} KB HTML</span>}
          </header>
          <div className="preview-toolbar">
            <div className="preview-format-switch">
              <button type="button" className={previewFormat === 'html' ? 'is-active' : ''} onClick={() => setPreviewFormat('html')}>Visual HTML</button>
              <button type="button" className={previewFormat === 'plain' ? 'is-active' : ''} onClick={() => setPreviewFormat('plain')} disabled={!preview}>Plain text</button>
            </div>
            {previewFormat === 'html' && <span className="viewport-switch">
              {!compactPreview && <button type="button" className={activePreviewWidth === 'desktop' ? 'is-active' : ''} onClick={() => setPreviewWidth('desktop')}><Monitor size={14} /> Desktop</button>}
              <button type="button" className={activePreviewWidth === 'mobile' ? 'is-active' : ''} onClick={() => setPreviewWidth('mobile')}><Smartphone size={14} /> Mobile</button>
            </span>}
          </div>
          {sdk.preview.loading && <PreviewLoadingSkeleton device={activePreviewWidth} label="Compiling the exact email HTML" />}
          {!sdk.preview.loading && previewError && <div className="preview-error"><strong>Preview could not be generated</strong><span>{previewError}</span><button type="button" className="button button--secondary" onClick={retryPreview}>Try again</button></div>}
          {!sdk.preview.loading && preview && preview.issues.length > 0 && <div className="preview-issues">{preview.issues.slice(0, 4).map((issue) => <span key={issue.code + ':' + (issue.node_id || '')}>{issue.message}</span>)}</div>}
          {!sdk.preview.loading && preview && previewFormat === 'html' && <div className={'preview-frame is-' + activePreviewWidth}><PreviewMailChrome subject={preview.subject || document.metadata.subject} preheader={document.metadata.preheader} device={activePreviewWidth}><CompiledPreviewFrame html={preview.html} device={activePreviewWidth} /></PreviewMailChrome></div>}
          {!sdk.preview.loading && preview && previewFormat === 'plain' && <div className="plain-preview"><pre>{preview.plain_text || 'No plain-text content was generated.'}</pre></div>}
        </div>
      </Modal>}

      {modal === 'revision-preview' && <Modal title={revisionPreview ? `Revision ${revisionPreview.revision_number} preview` : 'Revision preview'} onClose={closeModal} width={1160}>
        <div className="preview-dialog">
          <header className="preview-inbox">
            <span><small>Subject</small><strong>{revisionPreview?.subject || '(No subject)'}</strong></span>
            <span><small>Preheader</small><strong>{revisionPreview?.preheader || 'No preview text'}</strong></span>
            {revisionPreview && <span className="preview-size">{Math.max(1, Math.round(revisionPreview.bytes / 1024))} KB HTML</span>}
          </header>
          <div className="preview-toolbar">
            <div className="preview-format-switch">
              <button type="button" className={previewFormat === 'html' ? 'is-active' : ''} onClick={() => setPreviewFormat('html')}>Visual HTML</button>
              <button type="button" className={previewFormat === 'plain' ? 'is-active' : ''} onClick={() => setPreviewFormat('plain')} disabled={!revisionPreview}>Plain text</button>
            </div>
            <div className="revision-preview-actions">
              <button type="button" className="button button--secondary" onClick={backToHistory}>Back to history</button>
              {previewFormat === 'html' && <span className="viewport-switch">
                {!compactPreview && <button type="button" className={activePreviewWidth === 'desktop' ? 'is-active' : ''} onClick={() => setPreviewWidth('desktop')}><Monitor size={14} /> Desktop</button>}
                <button type="button" className={activePreviewWidth === 'mobile' ? 'is-active' : ''} onClick={() => setPreviewWidth('mobile')}><Smartphone size={14} /> Mobile</button>
              </span>}
            </div>
          </div>
          {sdk.revisionPreview.loading && <PreviewLoadingSkeleton device={activePreviewWidth} label="Loading revision preview" />}
          {!sdk.revisionPreview.loading && revisionPreviewError && <div className="preview-error"><strong>Revision preview could not be loaded</strong><span>{revisionPreviewError}</span><button type="button" className="button button--secondary" onClick={retryRevisionPreview}>Try again</button></div>}
          {!sdk.revisionPreview.loading && revisionPreview && revisionPreview.issues.length > 0 && <div className="preview-issues">{revisionPreview.issues.slice(0, 4).map((issue) => <span key={issue.code + ':' + (issue.node_id || '')}>{issue.message}</span>)}</div>}
          {!sdk.revisionPreview.loading && revisionPreview && previewFormat === 'html' && <div className={'preview-frame is-' + activePreviewWidth}><PreviewMailChrome subject={revisionPreview.subject} preheader={revisionPreview.preheader} device={activePreviewWidth}><CompiledPreviewFrame html={revisionPreview.html} device={activePreviewWidth} /></PreviewMailChrome></div>}
          {!sdk.revisionPreview.loading && revisionPreview && previewFormat === 'plain' && <div className="plain-preview"><pre>{revisionPreview.plain_text || 'No plain-text content was generated.'}</pre></div>}
        </div>
      </Modal>}

      {modal === 'test' && <Modal title="Send test email" onClose={closeModal} width={480}>
        <div className="dialog-form"><label><span>Recipient</span><input type="email" value={recipient} onChange={(event) => setRecipient(event.target.value)} placeholder="you@example.com" autoFocus /></label><p>One test email will be queued through Frappe Email Queue.</p><div><button type="button" className="button button--secondary" onClick={closeModal}>Cancel</button><button type="button" className="button button--primary" onClick={sendTestEmail} disabled={!recipient.trim() || sdk.testEmail.loading}>{sdk.testEmail.loading ? 'Queuing…' : 'Queue test email'}</button></div></div>
      </Modal>}

      {modal === 'save-component' && <Modal title="Save reusable content" onClose={closeModal} width={480}>
        <div className="dialog-form"><label><span>Name</span><input value={componentName} onChange={(event) => setComponentName(event.target.value)} autoFocus /></label><label><span>Category</span><select value={componentCategory} onChange={(event) => setComponentCategory(event.target.value)}>{COMPONENT_CATEGORIES.map((category) => <option key={category}>{category}</option>)}</select></label><div><button type="button" className="button button--secondary" onClick={closeModal}>Cancel</button><button type="button" className="button button--primary" onClick={saveReusableContent} disabled={!componentName.trim() || sdk.saveComponent.loading}>Save to library</button></div></div>
      </Modal>}

      {modal === 'history' && <Modal title="Revision history" onClose={closeModal} width={820}>
        {sdk.revisions.isLoading ? <Spinner label="Loading revisions" /> : sdk.revisions.error ? <div className="history-error"><strong>Revision history could not be loaded</strong><span>{getErrorMessage(sdk.revisions.error)}</span><button type="button" className="button button--secondary" onClick={retryRevisions}>Try again</button></div> : <div className="history-panel"><div className="history-summary"><span><strong>{revisions.length}</strong><small>saved revisions</small></span><p>Restore creates a new revision, so historical versions stay immutable.</p></div><div className="revision-list">{revisions.map((revision, index) => <RevisionCard key={revision.name} revision={revision} latest={index === 0} onPreview={previewRevisionByName} onRestore={restoreRevisionByName} />)}{!revisions.length && <p className="empty-dialog">No saved revisions yet.</p>}</div></div>}
      </Modal>}

      {modal === 'suggestions' && <Modal title="Builder suggestions" onClose={closeModal} width={720}>
        <div className="suggestions-dialog">
          {!suggestions.length ? <div className="suggestions-empty"><CheckCircle2 size={28} /><strong>No frontend suggestions right now</strong><span>The design has no obvious syntax, field, image, or link issues from the live editor checks.</span></div> : <>
            <div className="suggestions-summary"><AlertTriangle size={17} /><span><strong>{suggestions.length}</strong> item{suggestions.length === 1 ? '' : 's'} to review before sending.</span></div>
            {Object.entries(groupSuggestions(suggestions)).map(([category, rows]) => <section className="suggestions-group" key={category}>
              <h3>{category}</h3>
              {rows.map((suggestion) => <article className={`suggestion-card is-${suggestion.severity}`} key={suggestion.id}>
                <header><span>{suggestionSeverityLabel(suggestion.severity)}</span><strong>{suggestion.title}</strong></header>
                <p>{suggestion.message}</p>
                {Boolean(suggestion.fields?.length) && <div className="suggestion-fields">{suggestion.fields!.map((field) => <code key={field}>{field}</code>)}</div>}
              </article>)}
            </section>)}
          </>}
        </div>
      </Modal>}

      {recoveryDraft && <Modal title="Recover browser draft" onClose={discardRecoveryDraft} width={480}>
        <div className="dialog-form"><p>A newer unsaved design was found in this browser. Recover it to continue where you left off, or discard it and keep the saved template.</p><div><button type="button" className="button button--secondary" onClick={discardRecoveryDraft}>Discard draft</button><button type="button" className="button button--primary" onClick={restoreRecoveryDraft}>Recover draft</button></div></div>
      </Modal>}

      {overwriteConfirmationOpen && <Modal title="Replace manual HTML?" onClose={closeOverwriteConfirmation} width={480}>
        <div className="dialog-form"><p>Saving this visual design will replace the current manual HTML in the Email Template. Your visual builder schema will be saved as the new source of the email.</p><div><button type="button" className="button button--secondary" onClick={closeOverwriteConfirmation}>Cancel</button><button type="button" className="button button--primary" onClick={confirmOverwrite}>Replace HTML</button></div></div>
      </Modal>}


      {modal === 'shortcuts' && <Modal title="Keyboard shortcuts" onClose={closeModal} width={620}>
        <div className="shortcuts-dialog">
          <p>Use these shortcuts when your cursor is not inside a form field. Text formatting shortcuts work while editing text on the canvas.</p>
          <div className="shortcut-grid">
            {SHORTCUT_GROUPS.map((group) => <section key={group.title} className="shortcut-group"><h3>{group.title}</h3>{group.items.map(([keys, description]) => <div key={keys} className="shortcut-row"><kbd>{keys}</kbd><span>{description}</span></div>)}</section>)}
          </div>
        </div>
      </Modal>}


      {modal === 'reference-doctype-change' && pendingReferenceDoctypeChange && <Modal title="Change Reference DocType?" onClose={cancelReferenceDoctypeChange} width={560}>
        <div className="dialog-form reference-doctype-dialog">
          <p>This template already uses the current Reference DocType. Changing it can make merge fields or record conditions invalid.</p>
          <div className="reference-change-summary">
            <span><strong>{pendingReferenceDoctypeChange.mergeTokenCount}</strong><small>dynamic field token{pendingReferenceDoctypeChange.mergeTokenCount === 1 ? '' : 's'}</small></span>
            <span><strong>{pendingReferenceDoctypeChange.conditionCount}</strong><small>record condition{pendingReferenceDoctypeChange.conditionCount === 1 ? '' : 's'}</small></span>
            {pendingReferenceDoctypeChange.hasPreviewDocument && <span><strong>1</strong><small>sample document will be cleared</small></span>}
          </div>
          <p className="reference-change-target"><span>{pendingReferenceDoctypeChange.previousValue || 'No DocType'}</span><i>→</i><span>{pendingReferenceDoctypeChange.nextValue || 'No DocType'}</span></p>
          <div className="reference-change-options">
            <button type="button" className="button button--secondary" onClick={cancelReferenceDoctypeChange}>Cancel</button>
            <button type="button" className="button button--secondary" onClick={keepReferenceDependentContent}>Keep content, turn validation off</button>
            <button type="button" className="button button--primary" onClick={removeReferenceDependentFields}>Remove fields & conditions</button>
          </div>
        </div>
      </Modal>}


      {modal === 'visual-unlock' && <Modal title="Edit Raw HTML visually?" onClose={closeModal} width={520}>
        <div className="dialog-form"><p>This Email Template is currently in Raw HTML mode, so the visual builder is opened read-only to protect the manual HTML.</p><p>If you continue, visual editing will unlock in this browser. The current manual HTML is not replaced until you explicitly save and confirm the overwrite.</p><div><button type="button" className="button button--secondary" onClick={closeModal}>Keep read-only</button><button type="button" className="button button--primary" onClick={confirmVisualEditing}>Edit visually</button></div></div>
      </Modal>}

      {modal === 'conflict' && <Modal title="Newer template version available" onClose={closeModal} width={500}>
        <div className="dialog-form"><p>Another editor saved this template after you opened it. Your local work remains in this browser, but saving it now could overwrite newer content.</p><p>Reloading replaces this tab’s local changes with the latest saved template.</p><div><button type="button" className="button button--secondary" onClick={closeModal}>Keep local changes</button><button type="button" className="button button--primary" onClick={reloadLatest}>Reload latest</button></div></div>
      </Modal>}
    </>
  )
})
