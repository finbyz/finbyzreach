import { useCallback, useEffect, useReducer, useRef } from 'react'

import { createPanelState, isDrawerMode, isExclusivePanelState, panelReducer } from '../lib/panelState'
import type { InspectorTab, Selection, SidebarTab } from '../types'

function getAvailableWidth(element?: HTMLElement | null) {
  return Math.round(element?.getBoundingClientRect().width || window.visualViewport?.width || window.innerWidth || 1440)
}

function initialPanelState() {
  return createPanelState(getAvailableWidth())
}

export function useBuilderPanels() {
  const [state, dispatch] = useReducer(panelReducer, undefined, initialPanelState)
  const shellElementRef = useRef<HTMLDivElement | null>(null)

  const setShellElement = useCallback((element: HTMLDivElement | null) => {
    shellElementRef.current = element
    if (element) dispatch({ type: 'sync-layout', width: getAvailableWidth(element) })
  }, [])

  useEffect(() => {
    let frame = 0
    const syncPanels = () => {
      window.cancelAnimationFrame(frame)
      frame = window.requestAnimationFrame(() => {
        dispatch({ type: 'sync-layout', width: getAvailableWidth(shellElementRef.current) })
      })
    }
    syncPanels()

    const observer = typeof ResizeObserver !== 'undefined' && shellElementRef.current
      ? new ResizeObserver(syncPanels)
      : null
    if (observer && shellElementRef.current) observer.observe(shellElementRef.current)

    window.addEventListener('resize', syncPanels)
    window.visualViewport?.addEventListener('resize', syncPanels)
    return () => {
      window.cancelAnimationFrame(frame)
      observer?.disconnect()
      window.removeEventListener('resize', syncPanels)
      window.visualViewport?.removeEventListener('resize', syncPanels)
    }
  }, [])

  const exclusivePanels = isExclusivePanelState(state)

  const setSelection = useCallback((value: Selection) => dispatch({ type: 'set-selection', value }), [])
  const setSidebarTab = useCallback((value: SidebarTab) => dispatch({ type: 'set-sidebar-tab', value }), [])
  const setInspectorTab = useCallback((value: InspectorTab) => dispatch({ type: 'set-inspector-tab', value }), [])
  const setInspectorOpen = useCallback((value: boolean) => dispatch({ type: 'set-inspector-open', value }), [])
  const select = useCallback((next: Selection) => dispatch({ type: 'select-node', value: next }), [])
  const openTemplateInspector = useCallback(() => dispatch({ type: 'open-template-inspector' }), [])
  const requestAddBlock = useCallback((columnId: string) => dispatch({ type: 'request-add-block', columnId }), [])
  const editSection = useCallback((sectionId: string, tab: 'content' | 'visibility') => dispatch({ type: 'edit-section', sectionId, tab }), [])
  const toggleSidebar = useCallback(() => dispatch({ type: 'toggle-sidebar' }), [])
  const toggleInspector = useCallback(() => dispatch({ type: 'toggle-inspector' }), [])
  const closePanels = useCallback(() => dispatch({ type: 'patch', value: { sidebarOpen: false, inspectorOpen: false } }), [])
  const closeInspector = useCallback(() => setInspectorOpen(false), [setInspectorOpen])
  const toggleStructure = useCallback(() => dispatch({ type: 'toggle-structure' }), [])
  const showDesktopViewport = useCallback(() => {
    if (!isDrawerMode(state.uiMode)) dispatch({ type: 'set-viewport', value: 'desktop' })
  }, [state.uiMode])
  const showMobileViewport = useCallback(() => dispatch({ type: 'set-viewport', value: 'mobile' }), [])

  return {
    ...state,
    exclusivePanels,
    setShellElement,
    setSelection,
    setSidebarTab,
    setInspectorTab,
    select,
    openTemplateInspector,
    requestAddBlock,
    editSection,
    toggleSidebar,
    toggleInspector,
    closePanels,
    closeInspector,
    toggleStructure,
    showDesktopViewport,
    showMobileViewport,
  }
}
