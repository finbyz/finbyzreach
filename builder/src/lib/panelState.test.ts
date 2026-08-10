import assert from 'node:assert/strict'
import test from 'node:test'

import {
  canDockBothPanels,
  createPanelState,
  getUiMode,
  isExclusivePanelState,
  panelReducer,
  syncPanelLayout,
} from './panelState.ts'

test('responsive UI mode is derived from workspace width boundaries', () => {
  assert.equal(getUiMode(360), 'mobile')
  assert.equal(getUiMode(899), 'mobile')
  assert.equal(getUiMode(900), 'tablet')
  assert.equal(getUiMode(1119), 'tablet')
  assert.equal(getUiMode(1120), 'laptop')
  assert.equal(getUiMode(1365), 'laptop')
  assert.equal(getUiMode(1366), 'desktop')
  assert.equal(getUiMode(1599), 'desktop')
  assert.equal(getUiMode(1600), 'wide')
})

test('initial panel layout keeps both sidebars only when canvas has safe width', () => {
  const wide = createPanelState(1700)
  assert.equal(wide.uiMode, 'wide')
  assert.equal(wide.sidebarOpen, true)
  assert.equal(wide.inspectorOpen, true)
  assert.equal(isExclusivePanelState(wide), false)

  const laptop = createPanelState(1280)
  assert.equal(laptop.uiMode, 'laptop')
  assert.equal(laptop.sidebarOpen, true)
  assert.equal(laptop.inspectorOpen, true)
  assert.equal(canDockBothPanels(1280, 'laptop'), true)

  const compactTablet = createPanelState(1024)
  assert.equal(compactTablet.uiMode, 'tablet')
  assert.equal(compactTablet.sidebarOpen, false)
  assert.equal(compactTablet.inspectorOpen, true)
  assert.equal(isExclusivePanelState(compactTablet), true)

  const mobile = createPanelState(375)
  assert.equal(mobile.uiMode, 'mobile')
  assert.equal(mobile.viewport, 'mobile')
  assert.equal(mobile.sidebarOpen, false)
  assert.equal(mobile.inspectorOpen, false)
  assert.equal(isExclusivePanelState(mobile), true)
})

test('syncPanelLayout collapses panels predictably while resizing', () => {
  const desktop = createPanelState(1500)
  assert.equal(desktop.sidebarOpen, true)
  assert.equal(desktop.inspectorOpen, true)

  const tablet = syncPanelLayout(desktop, 1024)
  assert.equal(tablet.uiMode, 'tablet')
  assert.equal(tablet.sidebarOpen, false)
  assert.equal(tablet.inspectorOpen, true)

  const mobile = syncPanelLayout(tablet, 375)
  assert.equal(mobile.uiMode, 'mobile')
  assert.equal(mobile.viewport, 'mobile')
  assert.equal(mobile.sidebarOpen, false)
  assert.equal(mobile.inspectorOpen, false)

  const backToDesktop = syncPanelLayout(mobile, 1500)
  assert.equal(backToDesktop.uiMode, 'desktop')
  assert.equal(backToDesktop.sidebarOpen, true)
  assert.equal(backToDesktop.inspectorOpen, true)
})

test('exclusive panel mode opens one drawer at a time', () => {
  let state = createPanelState(1024)
  assert.equal(isExclusivePanelState(state), true)

  state = panelReducer(state, { type: 'toggle-sidebar' })
  assert.equal(state.sidebarOpen, true)
  assert.equal(state.inspectorOpen, false)

  state = panelReducer(state, { type: 'toggle-inspector' })
  assert.equal(state.sidebarOpen, false)
  assert.equal(state.inspectorOpen, true)
})

test('selecting content opens inspector without losing docked sidebar on wide screens', () => {
  const state = createPanelState(1700)
  const next = panelReducer(state, { type: 'select-node', value: { kind: 'block', id: 'block-1' } })
  assert.deepEqual(next.selection, { kind: 'block', id: 'block-1' })
  assert.equal(next.inspectorOpen, true)
  assert.equal(next.sidebarOpen, true)
  assert.equal(next.inspectorTab, 'content')
})

test('selecting content closes sidebar in exclusive layouts', () => {
  const state = panelReducer(createPanelState(1024), { type: 'toggle-sidebar' })
  assert.equal(state.sidebarOpen, true)
  assert.equal(state.inspectorOpen, false)

  const next = panelReducer(state, { type: 'select-node', value: { kind: 'block', id: 'block-1' } })
  assert.equal(next.sidebarOpen, false)
  assert.equal(next.inspectorOpen, true)
  assert.deepEqual(next.selection, { kind: 'block', id: 'block-1' })
})

test('request-add-block focuses target column and opens content palette', () => {
  const state = panelReducer(createPanelState(1024), { type: 'request-add-block', columnId: 'column-1' })
  assert.deepEqual(state.selection, { kind: 'column', id: 'column-1' })
  assert.equal(state.sidebarTab, 'content')
  assert.equal(state.sidebarOpen, true)
  assert.equal(state.inspectorOpen, false)
})

test('edit-section opens requested inspector tab and keeps panels stable', () => {
  const state = panelReducer(createPanelState(1700), { type: 'edit-section', sectionId: 'section-1', tab: 'visibility' })
  assert.deepEqual(state.selection, { kind: 'section', id: 'section-1' })
  assert.equal(state.inspectorTab, 'visibility')
  assert.equal(state.sidebarOpen, true)
  assert.equal(state.inspectorOpen, true)
})
