import { useEffect, useState } from 'react'

export type ThemeMode = 'light' | 'dark'

export function getResolvedTheme(): ThemeMode {
  try {
    const params = new URLSearchParams(window.location.search)
    const urlTheme = params.get('theme')
    if (urlTheme === 'dark' || urlTheme === 'light') return urlTheme


    if (window.parent && window.parent !== window) {
      try {
        const parentFrappe = (window.parent as unknown as { frappe?: { ui?: { get_current_theme?: () => string } } }).frappe
        const parentTheme = parentFrappe?.ui?.get_current_theme?.() ||
          window.parent.document.documentElement.getAttribute('data-theme') ||
          window.parent.document.documentElement.getAttribute('data-theme-mode')
        if (parentTheme === 'dark' || parentTheme === 'light') return parentTheme
        if (parentTheme === 'automatic') {
          return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
        }
      } catch {

      }
    }

   
    const docTheme = document.documentElement.getAttribute('data-theme')
    if (docTheme === 'dark' || docTheme === 'light') return docTheme

    
    const frappeBoot = (window as unknown as { frappe?: { boot?: { desk_theme?: string; user?: { desk_theme?: string } } } }).frappe?.boot
    const deskTheme = (frappeBoot?.desk_theme || frappeBoot?.user?.desk_theme || '').toLowerCase()
    if (deskTheme === 'dark' || deskTheme === 'light') return deskTheme
    if (deskTheme === 'automatic') {
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
    }

    
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
      return 'dark'
    }
  } catch {
    
  }

  return 'light'
}

export function applyThemeToDom(theme: ThemeMode) {
  try {
    document.documentElement.setAttribute('data-theme', theme)
    if (theme === 'dark') {
      document.documentElement.classList.add('dark')
      document.body?.classList?.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
      document.body?.classList?.remove('dark')
    }
  } catch {
    
  }
}

export function useBuilderTheme() {
  const [theme, setTheme] = useState<ThemeMode>(() => {
    const initial = getResolvedTheme()
    applyThemeToDom(initial)
    return initial
  })

  useEffect(() => {
    applyThemeToDom(theme)
  }, [theme])

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.data?.type === 'frappe-theme-change') {
        const next = event.data.theme === 'dark' ? 'dark' : 'light'
        setTheme(next)
      }
    }
    window.addEventListener('message', onMessage)


    let observer: MutationObserver | null = null
    try {
      if (window.parent && window.parent !== window && window.parent.document) {
        const parentRoot = window.parent.document.documentElement
        observer = new MutationObserver(() => {
          const next = getResolvedTheme()
          setTheme(next)
        })
        observer.observe(parentRoot, {
          attributes: true,
          attributeFilter: ['data-theme', 'data-theme-mode'],
        })
      }
    } catch {
      
    }

    
    let mq: MediaQueryList | null = null
    let onMediaChange: ((e: MediaQueryListEvent) => void) | null = null
    if (window.matchMedia) {
      mq = window.matchMedia('(prefers-color-scheme: dark)')
      onMediaChange = () => {
        const next = getResolvedTheme()
        setTheme(next)
      }
      mq.addEventListener('change', onMediaChange)
    }

    return () => {
      window.removeEventListener('message', onMessage)
      observer?.disconnect()
      if (mq && onMediaChange) {
        mq.removeEventListener('change', onMediaChange)
      }
    }
  }, [])

  return theme
}
