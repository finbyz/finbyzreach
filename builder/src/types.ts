export type DeviceVisibility = 'both' | 'desktop' | 'mobile'

export type Spacing = {
  top?: string
  right?: string
  bottom?: string
  left?: string
}

export type NodeStyle = {
  background?: string
  padding?: Spacing
  margin?: Spacing
  color?: string
  font_color?: string
  font_size?: string
  line_height?: string
  font_family?: string
  font_weight?: string
  font_style?: string
  text_decoration?: string
  align?: 'left' | 'center' | 'right'
  width?: string
  height?: string
  border_width?: string
  border_color?: string
  border_style?: 'solid' | 'dotted' | 'dashed'
  radius?: string
  button_padding_x?: string
  button_padding_y?: string
  button_background?: string
  button_text_color?: string
}

export type VisibilityCondition = {
  fieldname: string
  operator: 'equals' | 'not_equals' | 'contains' | 'not_contains' | 'empty' | 'not_empty'
  value: string
}

export type Visibility = {
  device: DeviceVisibility
  match: 'all' | 'any'
  conditions: VisibilityCondition[]
}

export type BlockType = 'text' | 'image' | 'button' | 'divider' | 'spacer' | 'social' | 'preview_url' | 'code'

export type BuilderBlock = {
  id: string
  type: BlockType
  content: Record<string, unknown>
  style: NodeStyle
  visibility: Visibility
}

export type BuilderColumn = {
  id: string
  style: NodeStyle
  blocks: BuilderBlock[]
}

export type LayoutType =
  | '1'
  | '1/2:1/2'
  | '1/3:1/3:1/3'
  | '1/3:2/3'
  | '2/3:1/3'
  | '1/4:1/4:1/4:1/4'
  | '1/4:3/4'
  | '3/4:1/4'

export type BuilderSection = {
  id: string
  saved_component?: string
  layout: LayoutType
  column_widths?: number[]
  vertical_align: 'top' | 'middle' | 'bottom'
  mobile_stack: 'stack' | 'reverse' | 'none'
  style: NodeStyle
  visibility: Visibility
  columns: BuilderColumn[]
}

export type BuilderSettings = {
  content_width: number
  body_background: string
  content_background: string
  font_family: string
  font_size: string
  text_color: string
  link_color: string
  link_decoration: 'none' | 'underline'
  button_background: string
  button_text_color: string
  button_radius: string
  section_padding: string
}

export type BuilderSchema = {
  version: 1
  settings: BuilderSettings
  sections: BuilderSection[]
}

export type BuilderMetadata = {
  subject: string
  preheader: string
  reference_doctype: string
  preview_document: string
  validate_dynamic_fields: boolean
}

export type BuilderDocument = {
  schema: BuilderSchema
  metadata: BuilderMetadata
}

export type BuilderLoadResponse = {
  name: string
  subject: string
  preheader: string
  mode: string
  schema: BuilderSchema
  modified: string
  reference_doctype: string
  preview_document: string
  validate_dynamic_fields?: boolean
  requires_overwrite_confirmation: boolean
  has_manual_html: boolean
  html_conflict: boolean
}

export type Selection =
  | { kind: 'section'; id: string }
  | { kind: 'column'; id: string }
  | { kind: 'block'; id: string }
  | null

export type Viewport = 'desktop' | 'mobile'

export type BuilderUiMode = 'wide' | 'desktop' | 'laptop' | 'tablet' | 'mobile'

export type SidebarTab = 'content' | 'rows' | 'layers' | 'saved'

export type InspectorTab = 'content' | 'style' | 'visibility'

export type ComponentSummary = {
  name: string
  component_name: string
  component_type: 'Block' | 'Section'
  category: string
  modified: string
}

export type MergeField = {
  fieldname: string
  label: string
  fieldtype: string
  options?: string
}

export type LinkMergeFieldsResponse = {
  link_fieldname: string
  target_doctype: string
  fields: MergeField[]
}

export type BuilderImageFile = {
  name: string
  file_name: string
  file_url: string
  thumbnail_url?: string
  file_size?: number
  file_type?: string
  attached_to_doctype?: string
  attached_to_name?: string
  is_attached_to_template?: boolean
}

export type BuilderImageListResponse = {
  rows: BuilderImageFile[]
  has_more: boolean
  next_start: number
  start: number
  page_length: number
}


export type RevisionSummary = {
  name: string
  revision_number: number
  subject: string
  preheader?: string
  save_note?: string
  creation: string
  creation_epoch?: number
  timezone?: string
  content_hash?: string
  html_bytes?: number
}

export type ApiResponse<T> = { message: T }

export type ValidationIssue = {
  severity: 'warning' | 'error' | string
  code: string
  node_id?: string | null
  message: string
}

export type SaveResult = {
  modified: string
  warnings: string[]
  issues: ValidationIssue[]
  bytes: number
  schema: BuilderSchema
  metadata: BuilderMetadata
}

export type PreviewResult = {
  subject: string
  html: string
  plain_text: string
  warnings: string[]
  issues: ValidationIssue[]
  bytes: number
}

export type RevisionPreviewResult = PreviewResult & {
  revision_number: number
  preheader: string
  creation: string
  creation_epoch?: number
  timezone?: string
}

export type ComponentDocument = {
  name: string
  component_name: string
  component_type: 'Block' | 'Section'
  category: string
  definition_json: string
}

export type AiSamplePrompt = {
  title: string
  prompt: string
}

export type AiBuilderSettings = {
  enabled: boolean
  rewrite_configured: boolean
  sample_prompts?: AiSamplePrompt[]
  chat_history?: ChatTurn[]
}

export type AiRewriteProposal = {
  proposal_id: string | null
  scope?: 'template' | 'section'
  target_kind?: 'template' | 'section'
  target_id?: string
  summary: string
  schema: BuilderSchema
  metadata: { subject: string; preheader: string }
  change_notes: string[]
  warnings: string[]
  preview_html: string
  preview_subject: string
  before_html: string
  before_subject: string
  issues: ValidationIssue[]
  status?: 'pending' | 'accepted' | 'rejected'
  thinking_steps?: { type: string; label: string; detail?: string }[]
}

export type ChatTurn = {
  id: string
  role: 'user' | 'assistant'
  text: string
  proposal?: AiRewriteProposal
  status?: 'pending' | 'accepted' | 'rejected'
  isError?: boolean
}
