import type { ComponentSummary, MergeField, RevisionSummary } from '../types'

export const HISTORY_LIMIT = 50
export const HISTORY_COALESCE_MS = 700
export const MAX_IMAGE_BYTES = 10 * 1024 * 1024
export const BUILDER_BREAKPOINTS = {
  mobile: 899,
  tablet: 1119,
  laptop: 1365,
  desktop: 1599,
} as const

export const BUILDER_PANEL_WIDTHS = {
  wide: { sidebar: 264, inspector: 326, minCanvas: 680 },
  desktop: { sidebar: 244, inspector: 306, minCanvas: 640 },
  laptop: { sidebar: 196, inspector: 276, minCanvas: 620 },
  tablet: { sidebar: 390, inspector: 390, minCanvas: 480 },
  mobile: { sidebar: 0, inspector: 0, minCanvas: 320 },
} as const


export const EMPTY_COMPONENTS: ComponentSummary[] = []
export const EMPTY_MERGE_FIELDS: MergeField[] = []
export const EMPTY_REVISIONS: RevisionSummary[] = []

export const BLOCK_LABELS: Record<string, string> = {
  text: 'Text',
  image: 'Image',
  button: 'Button',
  divider: 'Divider',
  spacer: 'Spacer',
  social: 'Social',
  preview_url: 'View online',
  code: 'HTML',
}
