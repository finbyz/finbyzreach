import { useCallback, useEffect, useReducer } from 'react'

import type { useBuilderData } from './useBuilderData'
import { getErrorMessage } from '../lib/errors'
import type { AiRewriteProposal, BuilderDocument, ChatTurn } from '../types'
import type { ModalName } from '../components/BuilderDialogs'
import type { NoticeKind, NoticeOptions } from '../components/notificationContext'

type Notify = (value: unknown, kind?: NoticeKind, options?: NoticeOptions) => void

type AiOptions = {
  document: BuilderDocument | null
  sdk: ReturnType<typeof useBuilderData>
  templateName: string
  notify: Notify
  setModal: (modal: ModalName) => void
  commit: (change: (next: BuilderDocument) => void, recordHistory?: boolean, historyKey?: string) => void
  isReadOnly: boolean
}

type AiScope = { type: 'template' } | { type: 'section'; sectionId: string }

type AiState = {
  prompt: string
  proposal: AiRewriteProposal | null
  error: string
  scope: AiScope
  chatTurns: ChatTurn[]
}

type AiAction =
  | { type: 'set-prompt'; value: string }
  | { type: 'set-proposal'; value: AiRewriteProposal; userText: string }
  | { type: 'set-error'; value: string; userText: string }
  | { type: 'clear-proposal' }
  | { type: 'set-scope'; scope: AiScope }
  | { type: 'accept-proposal'; proposalId?: string }
  | { type: 'reject-proposal'; proposalId?: string }
  | { type: 'set-turns'; turns: ChatTurn[] }
  | { type: 'reset' }

const INITIAL_AI_STATE: AiState = { prompt: '', proposal: null, error: '', scope: { type: 'template' }, chatTurns: [] }

function aiReducer(state: AiState, action: AiAction): AiState {
  switch (action.type) {
    case 'set-prompt':
      return { ...state, prompt: action.value }
    case 'set-proposal': {
      const userTurn: ChatTurn = { id: `u-${Date.now()}`, role: 'user', text: action.userText }
      const assistantTurn: ChatTurn = {
        id: action.value.proposal_id || `a-${Date.now()}`,
        role: 'assistant',
        text: action.value.summary || 'Here is the proposal:',
        proposal: action.value,
        status: 'pending',
      }
      return {
        ...state,
        prompt: '',
        proposal: action.value,
        error: '',
        chatTurns: [...state.chatTurns, userTurn, assistantTurn],
      }
    }
    case 'set-error': {
      const userTurn: ChatTurn = { id: `u-${Date.now()}`, role: 'user', text: action.userText }
      return {
        ...state,
        error: action.value,
        proposal: null,
        chatTurns: [...state.chatTurns, userTurn],
      }
    }
    case 'clear-proposal':
      return { ...state, proposal: null, error: '' }
    case 'set-scope':
      return { ...state, scope: action.scope, proposal: null, error: '' }
    case 'accept-proposal':
      return {
        ...state,
        chatTurns: state.chatTurns.map((turn) =>
          turn.proposal && (turn.id === action.proposalId || turn.proposal.proposal_id === action.proposalId)
            ? { ...turn, status: 'accepted' }
            : turn
        ),
      }
    case 'reject-proposal':
      return {
        ...state,
        proposal: null,
        chatTurns: state.chatTurns.map((turn) =>
          turn.proposal && (turn.id === action.proposalId || turn.proposal.proposal_id === action.proposalId)
            ? { ...turn, status: 'rejected' }
            : turn
        ),
      }
    case 'set-turns':
      return { ...state, chatTurns: action.turns }
    case 'reset':
      return INITIAL_AI_STATE
  }
}

export function useBuilderAi({ document, sdk, templateName, notify, setModal, commit, isReadOnly }: AiOptions) {
  const [state, dispatch] = useReducer(aiReducer, INITIAL_AI_STATE)

  const enabled = Boolean(sdk.aiSettings.data?.message?.enabled)
  const samplePrompts = sdk.aiSettings.data?.message?.sample_prompts ?? []
  const savedHistory = sdk.aiSettings.data?.message?.chat_history
  const generating = sdk.aiRewrite.loading

  useEffect(() => {
    if (savedHistory && Array.isArray(savedHistory)) {
      dispatch({ type: 'set-turns', turns: savedHistory })
    }
  }, [savedHistory])

  const setAiPrompt = useCallback((value: string) => dispatch({ type: 'set-prompt', value }), [])

  const openAiRewrite = useCallback(() => {
    if (isReadOnly || !enabled) return
    dispatch({ type: 'set-scope', scope: { type: 'template' } })
    setModal('ai')
  }, [enabled, isReadOnly, setModal])

  const openAiSectionRewrite = useCallback((sectionId: string) => {
    if (isReadOnly || !enabled || !sectionId) return
    dispatch({ type: 'set-scope', scope: { type: 'section', sectionId } })
    setModal('ai')
  }, [enabled, isReadOnly, setModal])

  const closeAiRewrite = useCallback(() => {
    setModal(null)
    dispatch({ type: 'clear-proposal' })
  }, [setModal])

  const generate = useCallback(async () => {
    if (!document || isReadOnly) return
    const prompt = state.prompt.trim()
    if (!prompt) return
    const chatHistory = state.chatTurns.map((turn) => ({ role: turn.role, text: turn.text }))
    dispatch({ type: 'clear-proposal' })
    try {
      const response = await sdk.aiRewrite.call({
        template_name: templateName,
        schema: JSON.stringify(document.schema),
        metadata: JSON.stringify(document.metadata),
        prompt,
        scope: state.scope.type,
        section_id: state.scope.type === 'section' ? state.scope.sectionId : undefined,
        chat_history: JSON.stringify(chatHistory),
      })
      dispatch({ type: 'set-proposal', value: response.message, userText: prompt })
    } catch (error) {
      dispatch({ type: 'set-error', value: getErrorMessage(error, 'The AI rewrite could not be generated.'), userText: prompt })
    }
  }, [document, isReadOnly, sdk.aiRewrite, state.chatTurns, state.prompt, state.scope, templateName])

  const acceptProposal = useCallback(() => {
    if (!state.proposal || isReadOnly) return
    const { schema, metadata, proposal_id } = state.proposal
    commit((next) => {
      next.schema = schema
      next.metadata.subject = metadata.subject
      next.metadata.preheader = metadata.preheader
    }, true, '')
    if (proposal_id) {
      void sdk.aiAccept.call({ proposal_id, template_name: templateName }).catch(() => undefined)
    }
    dispatch({ type: 'accept-proposal', proposalId: proposal_id || undefined })
    dispatch({ type: 'clear-proposal' })
    notify(state.proposal.scope === 'section' ? 'AI row changes applied. Undo to revert, or Save to keep them.' : 'AI changes applied. Undo to revert, or Save to keep them.', 'success')
  }, [commit, isReadOnly, notify, sdk.aiAccept, state.proposal, templateName])

  const discardProposal = useCallback(() => {
    if (state.proposal?.proposal_id) {
      dispatch({ type: 'reject-proposal', proposalId: state.proposal.proposal_id })
    } else {
      dispatch({ type: 'clear-proposal' })
    }
  }, [state.proposal])

  const clearAiChat = useCallback(async () => {
    try {
      await sdk.aiClearChat.call({ template_name: templateName })
      dispatch({ type: 'set-turns', turns: [] })
      dispatch({ type: 'clear-proposal' })
      notify('AI chat history cleared.', 'success')
    } catch (error) {
      notify(getErrorMessage(error, 'Could not clear AI chat history.'), 'error')
    }
  }, [notify, sdk.aiClearChat, templateName])

  const runGenerate = useCallback(() => { void generate() }, [generate])

  const saveAiSamplePrompt = useCallback(async (title: string, promptText: string) => {
    try {
      await sdk.aiSaveSamplePrompt.call({ title, prompt: promptText })
      await sdk.aiSettings.mutate()
      notify('Saved new prompt chip.', 'success')
    } catch (error) {
      notify(getErrorMessage(error, 'Could not save prompt.'), 'error')
    }
  }, [notify, sdk.aiSaveSamplePrompt, sdk.aiSettings])

  return {
    aiEnabled: enabled,
    aiSamplePrompts: samplePrompts,
    aiPrompt: state.prompt,
    aiProposal: state.proposal,
    aiError: state.error,
    aiGenerating: generating,
    aiScope: state.scope,
    chatTurns: state.chatTurns,
    setAiPrompt,
    openAiRewrite,
    openAiSectionRewrite,
    closeAiRewrite,
    generateAiRewrite: runGenerate,
    acceptAiProposal: acceptProposal,
    discardAiProposal: discardProposal,
    clearAiChat,
    saveAiSamplePrompt,
  }
}
