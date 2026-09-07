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

type AiScope = { type: 'template' }

type AiState = {
  prompt: string
  proposal: AiRewriteProposal | null
  error: string
  scope: AiScope
  chatTurns: ChatTurn[]
  liveStep: string | null
}

type AiAction =
  | { type: 'set-prompt'; value: string }
  | { type: 'send-user-message'; text: string }
  | { type: 'receive-proposal'; value: AiRewriteProposal }
  | { type: 'receive-error'; value: string }
  | { type: 'set-proposal'; value: AiRewriteProposal; userText: string }
  | { type: 'set-active-proposal'; value: AiRewriteProposal }
  | { type: 'set-live-step'; value: string | null }
  | { type: 'set-error'; value: string; userText: string }
  | { type: 'clear-proposal' }
  | { type: 'set-scope'; scope: AiScope }
  | { type: 'accept-proposal'; proposalId?: string }
  | { type: 'reject-proposal'; proposalId?: string }
  | { type: 'set-turns'; turns: ChatTurn[] }
  | { type: 'reset' }

const INITIAL_AI_STATE: AiState = { prompt: '', proposal: null, error: '', scope: { type: 'template' }, chatTurns: [], liveStep: null }

function aiReducer(state: AiState, action: AiAction): AiState {
  switch (action.type) {
    case 'set-prompt':
      return { ...state, prompt: action.value }
    case 'send-user-message': {
      const userTurn: ChatTurn = { id: `u-${Date.now()}`, role: 'user', text: action.text }
      return {
        ...state,
        prompt: '',
        proposal: null,
        error: '',
        liveStep: null,
        chatTurns: [...state.chatTurns, userTurn],
      }
    }
    case 'receive-proposal': {
      const assistantTurn: ChatTurn = {
        id: action.value.proposal_id || `a-${Date.now()}`,
        role: 'assistant',
        text: action.value.summary || 'Here is the updated design:',
        proposal: action.value,
        status: 'pending',
      }
      return {
        ...state,
        proposal: action.value,
        error: '',
        liveStep: null,
        chatTurns: [...state.chatTurns, assistantTurn],
      }
    }
    case 'receive-error': {
      const errorTurn: ChatTurn = {
        id: `e-${Date.now()}`,
        role: 'assistant',
        text: action.value,
        isError: true,
      }
      return {
        ...state,
        error: action.value,
        proposal: null,
        liveStep: null,
        chatTurns: [...state.chatTurns, errorTurn],
      }
    }
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
        liveStep: null,
        chatTurns: [...state.chatTurns, userTurn, assistantTurn],
      }
    }
    case 'set-active-proposal':
      return {
        ...state,
        proposal: action.value,
        error: '',
      }
    case 'set-live-step':
      return {
        ...state,
        liveStep: action.value,
      }
    case 'set-error': {
      const userTurn: ChatTurn = { id: `u-${Date.now()}`, role: 'user', text: action.userText }
      const errorTurn: ChatTurn = {
        id: `e-${Date.now()}`,
        role: 'assistant',
        text: action.value,
        isError: true,
      }
      return {
        ...state,
        error: '',
        proposal: null,
        liveStep: null,
        chatTurns: [...state.chatTurns, userTurn, errorTurn],
      }
    }
    case 'clear-proposal':
      return { ...state, proposal: null, error: '', liveStep: null }
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
  const generating = sdk.aiRewrite.loading || sdk.aiRunPreview.loading

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

  const closeAiRewrite = useCallback(() => {
    setModal(null)
    dispatch({ type: 'clear-proposal' })
  }, [setModal])

  const generate = useCallback(async () => {
    if (!document || isReadOnly) return
    const prompt = state.prompt.trim()
    if (!prompt) return

    // Optimistically push user message immediately so it renders on the right
    dispatch({ type: 'send-user-message', text: prompt })
    dispatch({ type: 'set-live-step', value: 'Generating response...' })

    const chatHistory = [
      ...state.chatTurns.map((turn) => ({ role: turn.role, text: turn.text })),
      { role: 'user', text: prompt },
    ]

    try {
      const response = await sdk.aiRewrite.call({
        template_name: templateName,
        schema: JSON.stringify(document.schema),
        metadata: JSON.stringify(document.metadata),
        prompt,
        scope: 'template',
        chat_history: JSON.stringify(chatHistory),
      })
      dispatch({ type: 'receive-proposal', value: response.message })
    } catch (error) {
      dispatch({ type: 'receive-error', value: getErrorMessage(error, 'The AI rewrite could not be generated.') })
    }
  }, [document, isReadOnly, sdk.aiRewrite, state.chatTurns, state.prompt, templateName])

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
    setModal(null)
    notify('AI changes applied. Undo to revert, or Save to keep them.', 'success')
  }, [commit, isReadOnly, notify, sdk.aiAccept, setModal, state.proposal, templateName])

  const applyPastProposal = useCallback((proposal: AiRewriteProposal) => {
    if (!proposal?.schema || isReadOnly) return
    commit((next) => {
      next.schema = proposal.schema
      if (proposal.metadata?.subject) next.metadata.subject = proposal.metadata.subject
      if (proposal.metadata?.preheader) next.metadata.preheader = proposal.metadata.preheader
    }, true, '')
    if (proposal.proposal_id) {
      void sdk.aiAccept.call({ proposal_id: proposal.proposal_id, template_name: templateName }).catch(() => undefined)
    }
    dispatch({ type: 'accept-proposal', proposalId: proposal.proposal_id || undefined })
    dispatch({ type: 'clear-proposal' })
    setModal(null)
    notify('Version restored and applied to template.', 'success')
  }, [commit, isReadOnly, notify, sdk.aiAccept, setModal, templateName])

  const loadProposalPreview = useCallback(async (proposalId: string) => {
    if (!proposalId) return
    // If we are already viewing this proposal, toggle it off (close preview)
    if (state.proposal?.proposal_id === proposalId) {
      dispatch({ type: 'clear-proposal' })
      return
    }
    // Check if it's already in the chat turns memory with full HTML
    const existingTurn = state.chatTurns.find(
      (t) => t.proposal?.proposal_id === proposalId && t.proposal?.preview_html
    )
    if (existingTurn?.proposal) {
      dispatch({ type: 'set-active-proposal', value: existingTurn.proposal })
      return
    }
    try {
      const res = await sdk.aiRunPreview.call({ proposal_id: proposalId })
      if (res?.message) {
        dispatch({ type: 'set-active-proposal', value: res.message })
      }
    } catch (err) {
      notify(getErrorMessage(err, 'Could not load proposal preview.'), 'error')
    }
  }, [notify, sdk.aiRunPreview, state.chatTurns, state.proposal?.proposal_id])

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

  const handleAiStep = useCallback((event: { template_name?: string; step: { type: string; label: string; detail?: string } }) => {
    if (event?.step?.label) {
      dispatch({ type: 'set-live-step', value: event.step.label })
    }
  }, [])

  return {
    aiEnabled: enabled,
    aiSamplePrompts: samplePrompts,
    aiPrompt: state.prompt,
    aiProposal: state.proposal,
    aiError: state.error,
    aiGenerating: generating,
    aiLiveStep: state.liveStep,
    aiScope: state.scope,
    chatTurns: state.chatTurns,
    setAiPrompt,
    openAiRewrite,
    closeAiRewrite,
    generateAiRewrite: runGenerate,
    acceptAiProposal: acceptProposal,
    discardAiProposal: discardProposal,
    applyPastProposal,
    loadProposalPreview,
    clearAiProposal: () => dispatch({ type: 'clear-proposal' }),
    handleAiStep,
    clearAiChat,
    saveAiSamplePrompt,
  }
}
