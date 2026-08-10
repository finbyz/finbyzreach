import { useCallback, useState } from 'react'
import { KeyboardSensor, PointerSensor, useSensor, useSensors, type DragEndEvent, type DragStartEvent } from '@dnd-kit/core'
import { sortableKeyboardCoordinates } from '@dnd-kit/sortable'

import { BLOCK_LABELS } from '../lib/builderConstants'
import { findBlock, findColumn, findSection, moveBlock, moveSection } from '../lib/builder'
import type { BlockType, BuilderDocument, LayoutType } from '../types'

type ActiveDrag = { kind: string; label: string } | null
type Commit = (change: (next: BuilderDocument) => void, recordHistory?: boolean, historyKey?: string) => void
type Target = { columnId: string; index: number } | null

type BuilderDndOptions = {
  document: BuilderDocument | null
  commit: Commit
  addBlock: (type: BlockType, explicitColumnId?: string, index?: number) => void
  addSection: (layout?: LayoutType, index?: number) => void
  resolveTarget: (source: BuilderDocument, overData: Record<string, unknown> | undefined) => Target
  readOnly?: boolean
}

export function useBuilderDnd({ document, commit, addBlock, addSection, resolveTarget, readOnly = false }: BuilderDndOptions) {
  const [activeDrag, setActiveDrag] = useState<ActiveDrag>(null)

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  const onDragStart = useCallback((event: DragStartEvent) => {
    if (readOnly) return
    const data = event.active.data.current
    const kind = String(data?.kind || '')
    const label = kind === 'palette-block'
      ? BLOCK_LABELS[String(data?.blockType)] || 'Module'
      : kind === 'layer-block'
        ? String(data?.label || 'Module')
        : kind.includes('section')
          ? 'Row'
          : 'Content'
    setActiveDrag({ kind, label })
  }, [readOnly])

  const onDragEnd = useCallback((event: DragEndEvent) => {
    setActiveDrag(null)
    if (readOnly || !document || !event.over) return
    const active = event.active.data.current as Record<string, unknown> | undefined
    const over = event.over.data.current as Record<string, unknown> | undefined
    if (active?.kind === 'palette-section') {
      let index = document.schema.sections.length
      if (over?.kind === 'section') index = findSection(document.schema, String(over.sectionId))?.sectionIndex ?? index
      addSection(String(active.layout) as LayoutType, index)
      return
    }
    if (active?.kind === 'section' || active?.kind === 'layer-section') {
      const sectionId = String(active.sectionId)
      const targetId = over?.kind === 'section' || over?.kind === 'layer-section'
        ? String(over.sectionId)
        : over?.kind === 'column' || over?.kind === 'layer-column'
          ? findColumn(document.schema, String(over.columnId))?.section.id
          : over?.kind === 'block' || over?.kind === 'layer-block'
            ? findBlock(document.schema, String(over.blockId))?.section.id
            : ''
      if (!targetId || targetId === sectionId) return
      commit((next) => { moveSection(next.schema, sectionId, targetId) })
      return
    }
    if (active?.kind === 'palette-block') {
      const target = resolveTarget(document, over)
      if (target) addBlock(String(active.blockType) as BlockType, target.columnId, target.index)
      else addBlock(String(active.blockType) as BlockType)
      return
    }
    if (active?.kind === 'block' || active?.kind === 'layer-block') {
      const blockId = String(active.blockId)
      const target = resolveTarget(document, over)
      const layerColumnTarget = over?.kind === 'layer-column' ? { columnId: String(over.columnId), index: findColumn(document.schema, String(over.columnId))?.column.blocks.length ?? 0 } : null
      const layerBlockTarget = over?.kind === 'layer-block' ? findBlock(document.schema, String(over.blockId)) : null
      const finalTarget = target || layerColumnTarget || (layerBlockTarget ? { columnId: layerBlockTarget.column.id, index: layerBlockTarget.blockIndex } : null)
      if (!finalTarget) return
      const targetBlockId = over?.kind === 'block' || over?.kind === 'layer-block' ? String(over.blockId) : undefined
      commit((next) => { moveBlock(next.schema, blockId, finalTarget.columnId, targetBlockId) })
    }
  }, [addBlock, addSection, commit, document, readOnly, resolveTarget])

  return { activeDrag, setActiveDrag, sensors, onDragStart, onDragEnd }
}
