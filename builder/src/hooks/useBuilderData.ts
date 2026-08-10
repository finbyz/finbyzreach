import { useMemo } from 'react'
import {
  useFrappeFileUpload,
  useFrappeGetCall,
  useFrappePostCall,
} from 'frappe-react-sdk'

import { API_METHODS, builderCacheKey, makeCallKey } from '../lib/api'
import type {
  ApiResponse,
  AiBuilderSettings,
  AiRewriteProposal,
  BuilderLoadResponse,
  BuilderDocument,
  ComponentDocument,
  ComponentSummary,
  PreviewResult,
  RevisionPreviewResult,
  RevisionSummary,
  SaveResult,
  ValidationIssue,
  MergeField,
  BuilderImageFile,
  BuilderImageListResponse,
} from '../types'

export function useBuilderData(templateName: string, historyOpen = false, document?: BuilderDocument | null) {
  const loadParams = useMemo(() => ({ template_name: templateName }), [templateName])
  const load = useFrappeGetCall<ApiResponse<BuilderLoadResponse>>(
    API_METHODS.load,
    templateName ? loadParams : undefined,
    templateName ? builderCacheKey(templateName) : null,
    { shouldRetryOnError: false, revalidateOnFocus: false },
  )

  const componentParams = useMemo(() => ({ page_length: 50 }), [])
  const components = useFrappeGetCall<ApiResponse<ComponentSummary[]>>(
    API_METHODS.components,
    componentParams,
    makeCallKey(API_METHODS.components, componentParams),
    { shouldRetryOnError: false, revalidateOnFocus: false },
  )

  const revisionParams = useMemo(() => ({ template_name: templateName, page_length: 50 }), [templateName])
  const revisions = useFrappeGetCall<ApiResponse<RevisionSummary[]>>(
    API_METHODS.revisions,
    historyOpen && templateName ? revisionParams : undefined,
    historyOpen && templateName ? makeCallKey(API_METHODS.revisions, revisionParams) : null,
    { shouldRetryOnError: false, revalidateOnFocus: false, isPaused: () => !historyOpen || !templateName },
  )

  const referenceDoctype = String(document?.metadata?.reference_doctype || '').trim()
  const mergeFieldParams = useMemo(() => referenceDoctype ? { reference_doctype: referenceDoctype } : undefined, [referenceDoctype])
  const mergeFieldKey = useMemo(
    () => referenceDoctype && mergeFieldParams ? makeCallKey(API_METHODS.mergeFields, mergeFieldParams) : null,
    [mergeFieldParams, referenceDoctype],
  )
  const mergeFields = useFrappeGetCall<ApiResponse<MergeField[]>>(
    API_METHODS.mergeFields,
    mergeFieldParams,
    mergeFieldKey,
    { shouldRetryOnError: false, revalidateOnFocus: false, revalidateOnMount: true, dedupingInterval: 0 },
  )

  const aiSettingsParams = useMemo(() => templateName ? { template_name: templateName } : undefined, [templateName])
  const aiSettings = useFrappeGetCall<ApiResponse<AiBuilderSettings>>(
    API_METHODS.aiSettings,
    aiSettingsParams,
    templateName ? makeCallKey(API_METHODS.aiSettings, aiSettingsParams) : null,
    { shouldRetryOnError: false, revalidateOnFocus: false, revalidateOnMount: true },
  )

  return {
    load,
    components,
    revisions,
    save: useFrappePostCall<ApiResponse<SaveResult>>(API_METHODS.save),
    preview: useFrappePostCall<ApiResponse<PreviewResult>>(API_METHODS.preview),
    testEmail: useFrappePostCall<ApiResponse<{ status: string; warnings: string[]; issues: ValidationIssue[] }>>(API_METHODS.testEmail),
    saveComponent: useFrappePostCall<ApiResponse<{ name: string }>>(API_METHODS.saveComponent),
    loadComponent: useFrappePostCall<ApiResponse<ComponentDocument>>(API_METHODS.loadComponent),
    restoreRevision: useFrappePostCall<ApiResponse<{ modified: string }>>(API_METHODS.restoreRevision),
    revisionPreview: useFrappePostCall<ApiResponse<RevisionPreviewResult>>(API_METHODS.revisionPreview),
    listImages: useFrappePostCall<ApiResponse<BuilderImageListResponse>>(API_METHODS.listImages),
    attachImage: useFrappePostCall<ApiResponse<BuilderImageFile>>(API_METHODS.attachImage),
    fileUpload: useFrappeFileUpload(),
    mergeFields,
    aiSettings,
    aiRewrite: useFrappePostCall<ApiResponse<AiRewriteProposal>>(API_METHODS.aiRewrite),
    aiAccept: useFrappePostCall<ApiResponse<{ ok: boolean }>>(API_METHODS.aiAccept),
    aiClearChat: useFrappePostCall<ApiResponse<{ ok: boolean }>>(API_METHODS.aiClearChat),
    aiSaveSamplePrompt: useFrappePostCall<ApiResponse<{ name: string }>>(API_METHODS.aiSaveSamplePrompt),
  }
}
