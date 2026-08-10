import { FileCode2, Image, Link, Minus, MousePointerClick, MoveVertical, Share2, Type, type LucideIcon } from 'lucide-react'

import type { BlockType } from '../types'

export const blockIcons: Record<BlockType, LucideIcon> = {
  text: Type,
  image: Image,
  button: MousePointerClick,
  divider: Minus,
  spacer: MoveVertical,
  social: Share2,
  preview_url: Link,
  code: FileCode2,
}
