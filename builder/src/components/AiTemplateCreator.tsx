import { useState, type FormEvent } from 'react'
import { ArrowLeft, ChevronDown, ChevronUp, Loader2, Sparkles, Wand2 } from 'lucide-react'
import { useFrappePostCall } from 'frappe-react-sdk'
import { API_METHODS } from '../lib/api'
import { getErrorMessage } from '../lib/errors'
import type { ApiResponse, BuilderTemplateDoctype } from '../types'

const SAMPLE_PROMPTS = [
  {
    title: '🚀 Product Launch',
    prompt: 'Product launch announcement with an eye-catching hero banner, headline, 3 feature columns with icons, customer quote, and a high-contrast "Try It Free" button.',
  },
  {
    title: '👋 Welcome Onboarding',
    prompt: 'Warm welcome email for new customers introducing our platform, 3 quick-start steps in clean cards, helpful documentation links, and a support contact section.',
  },
  {
    title: '📰 Monthly Newsletter',
    prompt: 'Modern company newsletter featuring top monthly highlights, a featured customer success story, upcoming webinar dates, and social media footer links.',
  },
  {
    title: '🏷️ Special Promotion',
    prompt: 'Limited-time discount email with an urgency banner, bold discount headline, 2-column product showcase, countdown mention, and a prominent "Claim 20% Off" CTA.',
  },
  {
    title: '📅 Event Invitation',
    prompt: 'Professional webinar invitation with speaker introduction, key agenda takeaways in bullet points, event date/time block, and a "Reserve Your Spot" button.',
  },
]

type AiTemplateCreatorProps = {
  mode?: 'page' | 'modal'
  onClose?: () => void
  templateDoctype?: BuilderTemplateDoctype
}

export function AiTemplateCreator({ mode = 'page', onClose, templateDoctype = 'Email Template' }: AiTemplateCreatorProps) {
  const [prompt, setPrompt] = useState('')
  const [templateName, setTemplateName] = useState('')
  const [subject, setSubject] = useState('')
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { call: createTemplateCall } = useFrappePostCall<
    ApiResponse<{ name: string; route: string; subject: string; summary?: string }>
  >(API_METHODS.aiCreateTemplate)

  const handleSubmit = async (e?: FormEvent) => {
    if (e) e.preventDefault()
    const cleanPrompt = prompt.trim()
    if (!cleanPrompt || loading) return

    setLoading(true)
    setError(null)

    try {
      const response = await createTemplateCall({
        prompt: cleanPrompt,
        template_doctype: templateDoctype,
        template_name: templateName.trim() || undefined,
        subject: subject.trim() || undefined,
      })

      const message = response?.message
      if (message && message.route) {
        window.location.href = message.route
      } else {
        throw new Error('No template route returned by server')
      }
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to generate email template. Please try again.')
      setLoading(false)
    }
  }

  const content = (
    <div className={`ai-creator-card${mode === 'modal' ? ' is-modal' : ''}`}>
      <div className="ai-creator-header">
        <div className="ai-creator-icon">
          <Sparkles size={24} />
        </div>
        <div className="ai-creator-title-block">
          <h2>Build {templateDoctype === 'Email Template Master' ? 'Master Template' : 'Email Template'} with AI ✨</h2>
          <p>
            Describe your email concept. AI will design a responsive layout, write persuasive copy, generate custom visuals, and launch the builder ready to customize.
          </p>
        </div>
        {mode === 'modal' && onClose && (
          <button type="button" className="icon-button ai-creator-close" onClick={onClose} aria-label="Close dialog">
            ✕
          </button>
        )}
      </div>

      <form onSubmit={handleSubmit} className="ai-creator-form">
        <div className="ai-creator-field">
          <label htmlFor="ai-creator-prompt">
            What kind of email do you want to build?
          </label>
          <textarea
            id="ai-creator-prompt"
            className="ai-creator-textarea"
            rows={4}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="e.g. Modern welcome email for MegaSol Solar Solutions with a friendly greeting, 3 key solar benefits in columns, customer testimonial, and a consultation CTA button."
            disabled={loading}
            autoFocus
          />
        </div>

        <div className="ai-creator-chips">
          <span className="ai-creator-chips-label">Quick inspiration:</span>
          <div className="ai-creator-chips-list">
            {SAMPLE_PROMPTS.map((chip) => (
              <button
                key={chip.title}
                type="button"
                className="ai-chip-button"
                onClick={() => setPrompt(chip.prompt)}
                disabled={loading}
              >
                {chip.title}
              </button>
            ))}
          </div>
        </div>

        <div className="ai-creator-advanced-toggle">
          <button
            type="button"
            className="button button--tertiary button--sm"
            onClick={() => setShowAdvanced(!showAdvanced)}
            disabled={loading}
          >
            {showAdvanced ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            <span>{showAdvanced ? 'Hide optional details' : 'Customize template name & subject (optional)'}</span>
          </button>
        </div>

        {showAdvanced && (
          <div className="ai-creator-advanced-fields">
            <div className="ai-creator-field">
              <label htmlFor="ai-creator-name">Template Name (optional)</label>
              <input
                id="ai-creator-name"
                type="text"
                className="input"
                value={templateName}
                onChange={(e) => setTemplateName(e.target.value)}
                placeholder="Leave blank to auto-generate from prompt"
                disabled={loading}
              />
            </div>
            <div className="ai-creator-field">
              <label htmlFor="ai-creator-subject">Subject Line (optional)</label>
              <input
                id="ai-creator-subject"
                type="text"
                className="input"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                placeholder="Leave blank to auto-generate from prompt"
                disabled={loading}
              />
            </div>
          </div>
        )}

        {error && (
          <div className="ai-creator-error" role="alert">
            <span>{error}</span>
          </div>
        )}

        <div className="ai-creator-actions">
          {mode === 'modal' && onClose ? (
            <button type="button" className="button button--secondary" onClick={onClose} disabled={loading}>
              Cancel
            </button>
          ) : (
            <a href={templateDoctype === 'Email Template Master' ? '/app/email-template-master' : '/app/email-template'} className="button button--secondary">
              <ArrowLeft size={14} />
              <span>Back to Desk</span>
            </a>
          )}

          <button
            type="submit"
            className="button button--primary button--ai-create"
            disabled={!prompt.trim() || loading}
          >
            {loading ? (
              <>
                <Loader2 size={16} className="animate-spin" />
                <span>Designing your email template...</span>
              </>
            ) : (
              <>
                <Wand2 size={16} />
                <span>Generate & Open Builder ✨</span>
              </>
            )}
          </button>
        </div>
      </form>
    </div>
  )

  if (mode === 'modal') {
    return (
      <div className="modal-backdrop" onClick={onClose}>
        <div className="modal-container" onClick={(e) => e.stopPropagation()}>
          {content}
        </div>
      </div>
    )
  }

  return (
    <div className="ai-creator-page">
      <div className="ai-creator-container">{content}</div>
    </div>
  )
}
