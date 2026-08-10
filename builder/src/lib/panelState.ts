import { BUILDER_BREAKPOINTS, BUILDER_PANEL_WIDTHS } from './builderConstants.ts'
import type { BuilderUiMode, InspectorTab, Selection, SidebarTab, Viewport } from '../types'

export type PanelState = {
  selection: Selection
  viewport: Viewport
  uiMode: BuilderUiMode
  workspaceWidth: number
  sidebarOpen: boolean
  inspectorOpen: boolean
  sidebarTab: SidebarTab
  inspectorTab: InspectorTab
  showStructure: boolean
}

export type PanelAction =
  | { type: 'patch'; value: Partial<PanelState> }
  | { type: 'sync-layout'; width: number }
  | { type: 'set-selection'; value: Selection }
  | { type: 'set-sidebar-tab'; value: SidebarTab }
  | { type: 'set-inspector-tab'; value: InspectorTab }
  | { type: 'set-inspector-open'; value: boolean }
  | { type: 'set-viewport'; value: Viewport }
  | { type: 'toggle-structure' }
  | { type: 'select-node'; value: Selection }
  | { type: 'open-template-inspector' }
  | { type: 'request-add-block'; columnId: string }
  | { type: 'edit-section'; sectionId: string; tab: 'content' | 'visibility' }
  | { type: 'toggle-sidebar' }
  | { type: 'toggle-inspector' }

export function getUiMode(width: number): BuilderUiMode {
  if (width <= BUILDER_BREAKPOINTS.mobile) return 'mobile'
  if (width <= BUILDER_BREAKPOINTS.tablet) return 'tablet'
  if (width <= BUILDER_BREAKPOINTS.laptop) return 'laptop'
  if (width <= BUILDER_BREAKPOINTS.desktop) return 'desktop'
  return 'wide'
}

export function isDrawerMode(mode: BuilderUiMode) {
  return mode === 'mobile'
}

export function canDockBothPanels(width: number, mode: BuilderUiMode) {
  if (isDrawerMode(mode)) return false
  const panel = BUILDER_PANEL_WIDTHS[mode]
  return width - panel.sidebar - panel.inspector >= panel.minCanvas
}

export function isExclusivePanelState(state: PanelState) {
  return isDrawerMode(state.uiMode) || !canDockBothPanels(state.workspaceWidth, state.uiMode)
}

export function createPanelState(workspaceWidth = 1440): PanelState {
  const uiMode = getUiMode(workspaceWidth)
  const dockBoth = canDockBothPanels(workspaceWidth, uiMode)
  const dockOne = !isDrawerMode(uiMode)
  return {
    selection: null,
    viewport: isDrawerMode(uiMode) ? 'mobile' : 'desktop',
    uiMode,
    workspaceWidth,
    sidebarOpen: dockBoth,
    inspectorOpen: dockOne,
    sidebarTab: 'content',
    inspectorTab: 'content',
    showStructure: false,
  }
}

export function syncPanelLayout(state: PanelState, width: number): PanelState {
  const uiMode = getUiMode(width)
  const modeChanged = uiMode !== state.uiMode
  const drawer = isDrawerMode(uiMode)
  const dockBoth = canDockBothPanels(width, uiMode)

  if (drawer) {
    return {
      ...state,
      uiMode,
      workspaceWidth: width,
      viewport: 'mobile',
      sidebarOpen: modeChanged ? false : state.sidebarOpen,
      inspectorOpen: modeChanged ? false : state.inspectorOpen,
    }
  }

  if (modeChanged) {
    return {
      ...state,
      uiMode,
      workspaceWidth: width,
      sidebarOpen: dockBoth,
      inspectorOpen: true,
    }
  }

  if (!dockBoth && state.sidebarOpen && state.inspectorOpen) {
    return { ...state, uiMode, workspaceWidth: width, sidebarOpen: false }
  }

  return { ...state, uiMode, workspaceWidth: width }
}

export function panelReducer(state: PanelState, action: PanelAction): PanelState {
  switch (action.type) {
    case 'patch':
      return { ...state, ...action.value }
    case 'sync-layout':
      return syncPanelLayout(state, action.width)
    case 'set-selection':
      return { ...state, selection: action.value }
    case 'set-sidebar-tab':
      return { ...state, sidebarTab: action.value }
    case 'set-inspector-tab':
      return { ...state, inspectorTab: action.value }
    case 'set-inspector-open':
      return { ...state, inspectorOpen: action.value }
    case 'set-viewport':
      return { ...state, viewport: action.value }
    case 'toggle-structure':
      return { ...state, showStructure: !state.showStructure }
    case 'select-node': {
      const exclusive = isExclusivePanelState(state)
      return {
        ...state,
        selection: action.value,
        ...(action.value ? { inspectorTab: 'content' as InspectorTab, inspectorOpen: true, sidebarOpen: exclusive ? false : state.sidebarOpen } : {}),
      }
    }
    case 'open-template-inspector': {
      const exclusive = isExclusivePanelState(state)
      return { ...state, selection: null, inspectorTab: 'content', inspectorOpen: true, sidebarOpen: exclusive ? false : state.sidebarOpen }
    }
    case 'request-add-block': {
      const exclusive = isExclusivePanelState(state)
      return {
        ...state,
        selection: { kind: 'column', id: action.columnId },
        sidebarTab: 'content',
        sidebarOpen: true,
        inspectorOpen: exclusive ? false : state.inspectorOpen,
      }
    }
    case 'edit-section': {
      const exclusive = isExclusivePanelState(state)
      return {
        ...state,
        selection: { kind: 'section', id: action.sectionId },
        inspectorTab: action.tab,
        inspectorOpen: true,
        sidebarOpen: exclusive ? false : state.sidebarOpen,
      }
    }
    case 'toggle-sidebar': {
      const exclusive = isExclusivePanelState(state)
      const next = !state.sidebarOpen
      return { ...state, sidebarOpen: next, inspectorOpen: next && exclusive ? false : state.inspectorOpen }
    }
    case 'toggle-inspector': {
      const exclusive = isExclusivePanelState(state)
      const next = !state.inspectorOpen
      return { ...state, inspectorOpen: next, sidebarOpen: next && exclusive ? false : state.sidebarOpen }
    }
  }
}
