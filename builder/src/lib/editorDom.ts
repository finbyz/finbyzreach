type LegacyEditorCommand = (commandId: string, showUI?: boolean, value?: string) => boolean

function activeRange() {
  const selection = window.getSelection()
  if (!selection?.rangeCount) return null
  return { selection, range: selection.getRangeAt(0) }
}

function collapseAfter(selection: Selection, range: Range, node: Node) {
  range.setStartAfter(node)
  range.collapse(true)
  selection.removeAllRanges()
  selection.addRange(range)
}

export function insertTextAtSelection(text: string) {
  const active = activeRange()
  if (!active) return false
  const textNode = document.createTextNode(text)
  active.range.deleteContents()
  active.range.insertNode(textNode)
  collapseAfter(active.selection, active.range, textNode)
  return true
}

export function insertLineBreakAtSelection() {
  const active = activeRange()
  if (!active) return false
  const lineBreak = document.createElement('br')
  active.range.deleteContents()
  active.range.insertNode(lineBreak)
  collapseAfter(active.selection, active.range, lineBreak)
  return true
}

export function runLegacyEditorCommand(command: string, value?: string) {
  const execCommand = Reflect.get(document, 'execCommand') as LegacyEditorCommand | undefined
  if (typeof execCommand !== 'function') return false
  return execCommand.call(document, command, false, value)
}
