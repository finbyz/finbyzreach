import { memo, useMemo, useRef, useState } from 'react'
import { useDraggable, useDroppable } from '@dnd-kit/core'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { Bookmark, Columns2, GripVertical, Layers3, Plus, Search, Trash2, X } from 'lucide-react'

import { BLOCKS, LAYOUTS } from '../lib/builder'
import type { BlockType, BuilderBlock, BuilderColumn, BuilderSchema, BuilderSection, ComponentSummary, LayoutType, Selection, SidebarTab } from '../types'
import { blockIcons } from '../lib/blockIcons'
import { EmptyState } from './ui'


type SidebarProps = {
  open: boolean
  schema: BuilderSchema
  selection: Selection
  components: ComponentSummary[]
  activeTab: SidebarTab
  onTab: (tab: SidebarTab) => void
  onAddBlock: (type: BlockType) => void
  onAddSection: (layout: LayoutType) => void
  onSelect: (selection: Selection) => void
  onDelete: (selection: NonNullable<Selection>) => void
  onInsertComponent: (name: string) => void
  onClose: () => void
  readOnly?: boolean
}

function DraggableBlock({ type, label, onClick, readOnly = false }: { type: BlockType; label: string; onClick: () => void; readOnly?: boolean }) {
  const dragged = useRef(false)
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `palette-block:${type}`,
    data: { kind: 'palette-block', blockType: type },
    disabled: readOnly,
  })
  const Icon = blockIcons[type]
  if (isDragging) dragged.current = true
  return (
    <button
      ref={setNodeRef}
      type="button"
      className={`module-card${isDragging ? ' is-dragging' : ''}`}
      disabled={readOnly}
      onClick={() => { if (readOnly || isDragging || dragged.current) { dragged.current = false; return } onClick() }}
      {...(readOnly ? {} : attributes)}
      {...(readOnly ? {} : listeners)}
    >
      <span><Icon size={17} /></span><strong>{label}</strong>
    </button>
  )
}


function MiniLayout({ widths }: { widths: number[] }) {
  return <span className="mini-layout">{widths.map((width, index) => <i key={index} style={{ flex: width }} />)}</span>
}

function DraggableRow({ layout, label, widths, onClick, readOnly = false }: { layout: LayoutType; label: string; widths: number[]; onClick: () => void; readOnly?: boolean }) {
  const dragged = useRef(false)
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `palette-section:${layout}`,
    data: { kind: 'palette-section', layout },
    disabled: readOnly,
  })
  if (isDragging) dragged.current = true
  return (
    <button
      ref={setNodeRef}
      type="button"
      className={`row-card${isDragging ? ' is-dragging' : ''}`}
      disabled={readOnly}
      onClick={() => { if (readOnly || isDragging || dragged.current) { dragged.current = false; return } onClick() }}
      {...(readOnly ? {} : attributes)}
      {...(readOnly ? {} : listeners)}
    >
      <MiniLayout widths={widths} /><strong>{label}</strong>
    </button>
  )
}

function LayerSectionRow({ section, sectionIndex, selection, onSelect, onDelete, readOnly }: {
  section: BuilderSection
  sectionIndex: number
  selection: Selection
  onSelect: SidebarProps['onSelect']
  onDelete: SidebarProps['onDelete']
  readOnly?: boolean
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: `layer-section:${section.id}`,
    data: { kind: 'layer-section', sectionId: section.id },
    disabled: readOnly,
  })
  return <div ref={setNodeRef} className={`layer-row is-section${isDragging ? ' is-dragging' : ''}`} style={{ transform: CSS.Transform.toString(transform), transition }}>
    <button type="button" className="layer-drag-handle" title="Drag row" aria-label={`Drag row ${sectionIndex + 1}`} disabled={readOnly} {...(readOnly ? {} : attributes)} {...(readOnly ? {} : listeners)}><GripVertical size={13} /></button>
    <button type="button" className={'layer-select' + (selection?.id === section.id ? ' is-active' : '')} onClick={() => onSelect({ kind: 'section', id: section.id })}><Columns2 size={14} /><span>Row {sectionIndex + 1}</span><small>{section.layout}</small></button>
    <button type="button" className="layer-delete" title="Delete row" aria-label={'Delete row ' + (sectionIndex + 1)} disabled={readOnly} onClick={() => { if (!readOnly) onDelete({ kind: 'section', id: section.id }) }}><Trash2 size={13} /></button>
  </div>
}

function LayerBlockRow({ block, selection, onSelect, onDelete, readOnly }: {
  block: BuilderBlock
  selection: Selection
  onSelect: SidebarProps['onSelect']
  onDelete: SidebarProps['onDelete']
  readOnly?: boolean
}) {
  const Icon = blockIcons[block.type]
  const label = BLOCKS.find((item) => item.type === block.type)?.label || block.type
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: `layer-block:${block.id}`,
    data: { kind: 'layer-block', blockId: block.id, label },
    disabled: readOnly,
  })
  return <div ref={setNodeRef} className={`layer-row is-block${isDragging ? ' is-dragging' : ''}`} style={{ transform: CSS.Transform.toString(transform), transition }}>
    <button type="button" className="layer-drag-handle" title="Drag content" aria-label={`Drag ${label}`} disabled={readOnly} {...(readOnly ? {} : attributes)} {...(readOnly ? {} : listeners)}><GripVertical size={13} /></button>
    <button type="button" className={'layer-select' + (selection?.id === block.id ? ' is-active' : '')} onClick={() => onSelect({ kind: 'block', id: block.id })}><Icon size={13} /><span>{label}</span></button>
    <button type="button" className="layer-delete" title="Delete content" aria-label="Delete content" disabled={readOnly} onClick={() => { if (!readOnly) onDelete({ kind: 'block', id: block.id }) }}><Trash2 size={13} /></button>
  </div>
}

function LayerColumn({ column, columnIndex, selection, onSelect, onDelete, readOnly }: {
  column: BuilderColumn
  columnIndex: number
  selection: Selection
  onSelect: SidebarProps['onSelect']
  onDelete: SidebarProps['onDelete']
  readOnly?: boolean
}) {
  const { setNodeRef, isOver } = useDroppable({
    id: `layer-column:${column.id}`,
    data: { kind: 'layer-column', columnId: column.id },
    disabled: readOnly,
  })
  return <div className={`layer-children${isOver ? ' is-over' : ''}`} ref={setNodeRef}>
    <button type="button" className={'layer-select' + (selection?.id === column.id ? ' is-active' : '')} onClick={() => onSelect({ kind: 'column', id: column.id })}>
      <span className="layer-dot" /><span>Column {columnIndex + 1}</span><small>{column.blocks.length}</small>
    </button>
    <SortableContext items={column.blocks.map((block) => `layer-block:${block.id}`)} strategy={verticalListSortingStrategy}>
      {column.blocks.map((block) => <LayerBlockRow key={block.id} block={block} selection={selection} onSelect={onSelect} onDelete={onDelete} readOnly={readOnly} />)}
    </SortableContext>
  </div>
}

function Layers({ schema, selection, onSelect, onDelete, readOnly }: Pick<SidebarProps, 'schema' | 'selection' | 'onSelect' | 'onDelete' | 'readOnly'>) {
  if (!schema.sections.length) return <EmptyState title="No layers yet" description="Add a row and content to build the hierarchy." />
  return (
    <div className="layer-tree">
      <SortableContext items={schema.sections.map((section) => `layer-section:${section.id}`)} strategy={verticalListSortingStrategy}>
        {schema.sections.map((section, sectionIndex) => (
          <div key={section.id} className="layer-section">
            <LayerSectionRow section={section} sectionIndex={sectionIndex} selection={selection} onSelect={onSelect} onDelete={onDelete} readOnly={readOnly} />
            {section.columns.map((column, columnIndex) => <LayerColumn key={column.id} column={column} columnIndex={columnIndex} selection={selection} onSelect={onSelect} onDelete={onDelete} readOnly={readOnly} />)}
          </div>
        ))}
      </SortableContext>
    </div>
  )
}

export const Sidebar = memo(function Sidebar(props: SidebarProps) {
  const [search, setSearch] = useState('')
  const modules = useMemo(() => BLOCKS.filter((item) => `${item.label} ${item.description}`.toLowerCase().includes(search.toLowerCase())), [search])
  return (
    <aside className={`builder-sidebar${props.open ? ' is-open' : ''}`} aria-label="Email content library">
      <div className="sidebar-topbar">
        <nav className="sidebar-tabs" aria-label="Builder library">
          {([
            ['content', Plus, 'Content'],
            ['rows', Columns2, 'Rows'],
            ['layers', Layers3, 'Layers'],
            ['saved', Bookmark, 'Saved'],
          ] as const).map(([tab, Icon, label]) => <button key={tab} type="button" className={props.activeTab === tab ? 'is-active' : ''} onClick={() => props.onTab(tab)}><Icon size={15} /><span>{label}</span></button>)}
        </nav>
        <button type="button" className="sidebar-close icon-button" onClick={props.onClose} aria-label="Close content library" title="Close"><X size={16} /></button>
      </div>
      <div className="sidebar-scroll">
        {props.activeTab === 'content' && <>
          <div className="panel-heading"><div><strong>Add content</strong><span>{BLOCKS.length} modules</span></div><p>Click a module or drag it into any column.</p></div>
          <label className="search-field"><Search size={15} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search modules" /></label>
          {props.readOnly && <div className="read-only-panel-note">Editing is locked. You can inspect this template, but content cannot be inserted yet.</div>}<div className="module-grid">{modules.map((item) => <DraggableBlock key={item.type} type={item.type} label={item.label} readOnly={props.readOnly} onClick={() => props.onAddBlock(item.type)} />)}</div>
        </>}
        {props.activeTab === 'rows' && <>
          <div className="panel-heading"><div><strong>Add row</strong><span>{LAYOUTS.length} layouts</span></div><p>Rows define the responsive column structure.</p></div>
          {props.readOnly && <div className="read-only-panel-note">Rows are locked until visual editing is enabled.</div>}<div className="row-grid">{LAYOUTS.map((item) => <DraggableRow key={item.value} layout={item.value} label={item.label} widths={item.widths} readOnly={props.readOnly} onClick={() => props.onAddSection(item.value)} />)}</div>
        </>}
        {props.activeTab === 'layers' && <><div className="panel-heading"><div><strong>Document layers</strong></div><p>Select or delete nested content without hunting on the canvas.</p></div><Layers schema={props.schema} selection={props.selection} onSelect={props.onSelect} onDelete={props.onDelete} readOnly={props.readOnly} /></>}
        {props.activeTab === 'saved' && <>
          <div className="panel-heading"><div><strong>Saved content</strong><span>{props.components.length}</span></div><p>Reusable blocks are copied into this email.</p></div>
          <div className="saved-list">{props.components.map((component) => <button type="button" key={component.name} disabled={props.readOnly} onClick={() => { if (!props.readOnly) props.onInsertComponent(component.name) }}><Bookmark size={15} /><span><strong>{component.component_name}</strong><small>{component.category} · {component.component_type}</small></span><Plus size={14} /></button>)}</div>
          {!props.components.length && <EmptyState title="No saved content" description="Select a row or module and save it from its toolbar." />}
        </>}
      </div>
    </aside>
  )
})

export type { SidebarTab }
