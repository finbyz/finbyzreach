import { useFrappeGetCall, useFrappePostCall } from 'frappe-react-sdk'
import { useState } from 'react'

import { API_METHODS } from '../lib/api'
import { useNotifications } from '../hooks/useNotifications'
import type { ApiResponse, BuilderSettings } from '../types'

// EM-14: design settings kept on the server so every e-mail (and every colleague) can use them.
const THEME_KEYS: Array<keyof BuilderSettings> = [
  'content_width', 'body_background', 'content_background', 'font_family', 'font_size', 'text_color', 'link_color',
  'link_decoration', 'button_background', 'button_text_color', 'button_radius', 'section_padding',
  'dark_mode', 'dark_body_background', 'dark_content_background', 'dark_text_color', 'dark_link_color',
  'h1_font_family', 'h1_font_size', 'h1_font_weight', 'h2_font_family', 'h2_font_size', 'h2_font_weight',
  'h3_font_family', 'h3_font_size', 'h3_font_weight', 'p_font_family', 'p_font_size', 'p_font_weight',
]

type ThemeRow = { name: string; theme_name: string; settings: Record<string, string | number> }

export function ThemePanel({ settings, readOnly, onSetting }: {
  settings: BuilderSettings
  readOnly?: boolean
  onSetting: (key: keyof BuilderSettings, value: string | number) => void
}) {
  const { notify } = useNotifications()
  const list = useFrappeGetCall<ApiResponse<ThemeRow[]>>(API_METHODS.listThemes, undefined, API_METHODS.listThemes, { shouldRetryOnError: false, revalidateOnFocus: false })
  const save = useFrappePostCall<ApiResponse<ThemeRow>>(API_METHODS.saveTheme)
  const remove = useFrappePostCall<ApiResponse<{ deleted: string }>>(API_METHODS.deleteTheme)
  const [selected, setSelected] = useState('')
  const [name, setName] = useState('')
  const themes = list.data?.message ?? []
  const current = themes.find((theme) => theme.name === selected)

  const apply = () => {
    if (!current) return
    for (const key of THEME_KEYS) {
      const value = current.settings[key]
      if (value !== undefined && value !== null) onSetting(key, value)
    }
    notify(`Theme “${current.theme_name}” applied. Save the e-mail to keep it.`, 'success')
  }
  const saveCurrent = async () => {
    const themeName = name.trim() || current?.theme_name || ''
    if (!themeName) { notify('Give the theme a name first.', 'warning'); return }
    const values: Record<string, string | number> = {}
    for (const key of THEME_KEYS) {
      const value = settings[key]
      if (value !== undefined && value !== null && value !== '') values[key] = value as string | number
    }
    try {
      await save.call({ theme_name: themeName, settings: JSON.stringify(values) })
      await list.mutate()
      setSelected(themeName)
      setName('')
      notify(`Theme “${themeName}” saved.`, 'success')
    } catch (error) {
      notify(error, 'error')
    }
  }
  const deleteSelected = async () => {
    if (!current) return
    try {
      await remove.call({ name: current.name })
      await list.mutate()
      setSelected('')
      notify(`Theme “${current.theme_name}” deleted.`, 'info')
    } catch (error) {
      notify(error, 'error')
    }
  }

  return <div className="theme-panel" data-testid="theme-panel">
    <label className="field"><span>Apply a saved theme</span>
      <select value={selected} onChange={(event) => setSelected(event.target.value)} aria-label="Saved theme">
        <option value="">{list.isLoading ? 'Loading…' : themes.length ? 'Choose a theme' : 'No themes saved yet'}</option>
        {themes.map((theme) => <option key={theme.name} value={theme.name}>{theme.theme_name}</option>)}
      </select>
    </label>
    <div className="button-row">
      <button type="button" className="secondary-button" disabled={readOnly || !current} onClick={apply}>Apply to this email</button>
      <button type="button" className="secondary-button" disabled={readOnly || !current || remove.loading} onClick={() => void deleteSelected()}>Delete theme</button>
    </div>
    <label className="field"><span>Save this design as a theme</span>
      <input value={name} placeholder={current ? `Name (empty replaces “${current.theme_name}”)` : 'Theme name'} onChange={(event) => setName(event.target.value)} aria-label="Theme name" />
    </label>
    <button type="button" className="secondary-button" disabled={readOnly || save.loading} onClick={() => void saveCurrent()}>{save.loading ? 'Saving…' : 'Save theme'}</button>
    <p className="helper-text">A theme keeps colors, fonts, button style and dark-mode colors. It never changes the content of an email.</p>
  </div>
}
