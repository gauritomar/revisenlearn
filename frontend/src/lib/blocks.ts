/** Conversion between the Tiptap document and the `note_blocks` rows.
 *
 *  Spec §3: a Note Block is "one paragraph / bullet / heading within a Note" —
 *  so list *items*, not lists, are the unit. Spec §4.1 fixes the supported set:
 *  paragraph, H1/H2/H3, bullet list, numbered list, quote, code block, divider,
 *  link. Nothing else.
 */
import type { JSONContent } from '@tiptap/react'
import type { Block } from './api'

export type DraftBlock = {
  id?: number | null
  position: number
  block_type: string
  text: string
  /** checklist_item blocks (consolidated addendum §2). */
  checked?: boolean
  /** `code_block` only: the grammar it is highlighted with. */
  language?: string | null
  /** One level of nesting: the index of the parent in this same payload. */
  parent_index?: number | null
}

type Serialised = {
  block_type: string
  text: string
  checked?: boolean
  language?: string | null
  parentIndex?: number | null
}

/** Flatten a Tiptap doc into a positional block list. */
export function docToBlocks(doc: JSONContent): Serialised[] {
  const out: Serialised[] = []

  for (const node of doc.content ?? []) {
    switch (node.type) {
      // Consolidated addendum §2 — a checklist item is a block of its own,
      // carrying its own checked state. The `- [ ]` marker stays in the text
      // so the note reads the same however it is opened, and so the backend
      // parses the same thing whether the item was typed or ticked.
      case 'taskList':
        for (const item of node.content ?? []) {
          out.push(taskBlock(item))
          // "One level of nesting only" — a list inside an item, and no
          // deeper. Anything further nested is flattened to that one level.
          const parentIndex = out.length - 1
          for (const child of item.content ?? []) {
            if (child.type !== 'taskList') continue
            for (const nested of child.content ?? []) {
              out.push({ ...taskBlock(nested), parentIndex })
            }
          }
        }
        break
      case 'heading': {
        const level = Math.min(3, Math.max(1, Number(node.attrs?.level ?? 1)))
        out.push({ block_type: `heading${level}`, text: textOf(node) })
        break
      }
      case 'bulletList':
        for (const item of node.content ?? []) {
          out.push({ block_type: 'bullet_list_item', text: textOf(item) })
        }
        break
      case 'orderedList':
        for (const item of node.content ?? []) {
          out.push({ block_type: 'numbered_list_item', text: textOf(item) })
        }
        break
      case 'blockquote':
        out.push({ block_type: 'quote', text: textOf(node) })
        break
      case 'codeBlock':
        // The language is the block's, not the text's: a note reopens in the
        // grammar it was written in rather than one guessed from the code.
        out.push({
          block_type: 'code_block',
          text: textOf(node),
          language: (node.attrs?.language as string) || null,
        })
        break
      case 'horizontalRule':
        out.push({ block_type: 'divider', text: '' })
        break
      // §3 — the automatic day marker in a long-running lesson note. It is
      // written by the backend, not the user, so it round-trips untouched.
      case 'dateDivider':
        out.push({ block_type: 'date_divider', text: String(node.attrs?.date ?? '') })
        break
      default:
        out.push({ block_type: 'paragraph', text: textOf(node) })
    }
  }

  // A single trailing empty paragraph is Tiptap's cursor parking spot, not
  // content the user wrote. Dropping it keeps the "new blocks" counter honest.
  while (
    out.length &&
    out[out.length - 1].block_type === 'paragraph' &&
    !out[out.length - 1].text.trim()
  ) {
    out.pop()
  }
  return out
}

function taskBlock(item: JSONContent): Serialised {
  const checked = item.attrs?.checked === true
  // Only the item's own paragraphs, never a nested list's text.
  const text = (item.content ?? [])
    .filter((child) => child.type !== 'taskList')
    .map(textOf)
    .join('')
  return {
    block_type: 'checklist_item',
    text: `- [${checked ? 'x' : ' '}] ${text}`,
    checked,
  }
}

function textOf(node: JSONContent): string {
  if (node.type === 'text') return node.text ?? ''
  return (node.content ?? []).map(textOf).join('')
}

/** Rebuild a Tiptap doc from stored blocks, regrouping consecutive list items. */
export function blocksToDoc(blocks: Block[]): JSONContent {
  const content: JSONContent[] = []
  let i = 0

  while (i < blocks.length) {
    const block = blocks[i]

    if (block.block_type === 'checklist_item') {
      // Consecutive items become one task list, children nested under the
      // item they belong to.
      const items: JSONContent[] = []
      const byId = new Map<number, JSONContent>()
      while (i < blocks.length && blocks[i].block_type === 'checklist_item') {
        const current = blocks[i]
        const node: JSONContent = {
          type: 'taskItem',
          attrs: { checked: current.checked === true },
          content: [paragraph(stripMarker(current.text))],
        }
        byId.set(current.id, node)
        const parent = current.parent_block_id === null || current.parent_block_id === undefined
          ? undefined
          : byId.get(current.parent_block_id)
        if (parent) {
          const nested = parent.content!.find((c) => c.type === 'taskList')
          if (nested) nested.content!.push(node)
          else parent.content!.push({ type: 'taskList', content: [node] })
        } else {
          items.push(node)
        }
        i++
      }
      content.push({ type: 'taskList', content: items })
      continue
    }

    if (block.block_type === 'bullet_list_item' || block.block_type === 'numbered_list_item') {
      const listType = block.block_type === 'bullet_list_item' ? 'bulletList' : 'orderedList'
      const items: JSONContent[] = []
      while (i < blocks.length && blocks[i].block_type === block.block_type) {
        items.push({ type: 'listItem', content: [paragraph(blocks[i].text)] })
        i++
      }
      content.push({ type: listType, content: items })
      continue
    }

    switch (block.block_type) {
      case 'heading1':
      case 'heading2':
      case 'heading3':
        content.push({
          type: 'heading',
          attrs: { level: Number(block.block_type.slice(-1)) },
          content: inline(block.text),
        })
        break
      case 'quote':
        content.push({ type: 'blockquote', content: [paragraph(block.text)] })
        break
      case 'code_block':
        content.push({
          type: 'codeBlock',
          attrs: { language: block.language ?? null },
          content: inline(block.text),
        })
        break
      case 'divider':
        content.push({ type: 'horizontalRule' })
        break
      case 'date_divider':
        content.push({ type: 'dateDivider', attrs: { date: block.text } })
        break
      default:
        content.push(paragraph(block.text))
    }
    i++
  }

  if (content.length === 0) content.push(paragraph(''))
  return { type: 'doc', content }
}

/** `- [x] Read the paper` → `Read the paper`. The marker is the storage
 *  format; the editor shows a real checkbox instead. */
export function stripMarker(text: string): string {
  const match = /^\s*[-*]\s*\[[ xX]\]\s*(.*)$/.exec(text ?? '')
  return match ? match[1] : (text ?? '')
}

const paragraph = (text: string): JSONContent => ({ type: 'paragraph', content: inline(text) })
const inline = (text: string): JSONContent[] | undefined =>
  text ? [{ type: 'text', text }] : undefined

/** Give each serialised block the id of the stored row it came from, so that
 *  `processed_hash` survives a save (spec §4.2: edited-after-processing must
 *  read as stale, not as brand new).
 *
 *  Identical text wins first — that is the block that genuinely did not change,
 *  wherever it moved to. Anything left over is matched by position, which
 *  covers the common case of editing a block in place. */
export function reconcile(
  serialised: Serialised[],
  existing: Block[],
): DraftBlock[] {
  const unused = new Set(existing.map((b) => b.id))
  const assigned: Array<number | null> = new Array(serialised.length).fill(null)

  const byText = new Map<string, number[]>()
  for (const b of existing) {
    const key = `${b.block_type} ${b.text}`
    if (!byText.has(key)) byText.set(key, [])
    byText.get(key)!.push(b.id)
  }

  serialised.forEach((s, idx) => {
    const key = `${s.block_type} ${s.text}`
    const pool = byText.get(key)
    while (pool && pool.length) {
      const id = pool.shift()!
      if (unused.has(id)) {
        assigned[idx] = id
        unused.delete(id)
        return
      }
    }
  })

  serialised.forEach((_, idx) => {
    if (assigned[idx] !== null) return
    const candidate = existing[idx]
    if (candidate && unused.has(candidate.id)) {
      assigned[idx] = candidate.id
      unused.delete(candidate.id)
    }
  })

  return serialised.map((s, idx) => ({
    id: assigned[idx],
    position: idx,
    block_type: s.block_type,
    text: s.text,
    checked: s.checked ?? false,
    language: s.language ?? null,
    // Resolved server-side against this same payload, so a child saved
    // alongside a brand-new parent still lands under it.
    parent_index: s.parentIndex ?? null,
  }))
}
