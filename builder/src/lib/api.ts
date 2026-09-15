export const API_METHODS = {
  load: 'finbyzreach.email_template_builder.api.load_builder',
  save: 'finbyzreach.email_template_builder.api.save_builder',
  preview: 'finbyzreach.email_template_builder.api.render_preview',
  testEmail: 'finbyzreach.email_template_builder.api.send_test_email',
  mergeFields: 'finbyzreach.email_template_builder.api.get_merge_fields',
  linkMergeFields: 'finbyzreach.email_template_builder.api.get_link_merge_fields',
  components: 'finbyzreach.email_template_builder.api.list_components',
  loadComponent: 'finbyzreach.email_template_builder.api.load_component',
  revisions: 'finbyzreach.email_template_builder.api.list_revisions',
  saveComponent: 'finbyzreach.email_template_builder.api.save_component',
  restoreRevision: 'finbyzreach.email_template_builder.api.restore_revision',
  revisionPreview: 'finbyzreach.email_template_builder.api.render_revision_preview',
  listImages: 'finbyzreach.email_template_builder.api.list_builder_images',
  attachImage: 'finbyzreach.email_template_builder.api.attach_builder_image',
  aiSettings: 'finbyzreach.email_template_builder.ai.get_builder_ai_settings',
  aiRewrite: 'finbyzreach.email_template_builder.ai.generate_ai_rewrite',
  aiAccept: 'finbyzreach.email_template_builder.ai.accept_ai_proposal',
  aiClearChat: 'finbyzreach.email_template_builder.ai.clear_builder_ai_chat',
  aiSaveSamplePrompt: 'finbyzreach.email_template_builder.ai.save_ai_sample_prompt',
  aiRunPreview: 'finbyzreach.email_template_builder.ai.get_ai_run_preview',
  aiCreateTemplate: 'finbyzreach.email_template_builder.ai.create_template_with_ai',
} as const

export type ApiParams = Record<string, string | number | boolean | null | undefined>

export function makeCallKey(method: string, params: ApiParams = {}) {
  const clean = Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== '')
  if (!clean.length) return `${method}?`
  return `${method}?${clean
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`)
    .join('&')}`
}

export const builderCacheKey = (templateName: string, templateDoctype = 'Email Template') => makeCallKey(API_METHODS.load, {
  template_name: templateName,
  template_doctype: templateDoctype,
})
