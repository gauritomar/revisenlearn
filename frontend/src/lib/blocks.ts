/** Conversion between the Tiptap document and the `note_blocks` rows.
 *
 *  Spec §3: a Note Block is "one paragraph / bullet / heading within a Note" —
 *  so list *items*, not lists, are the unit. Spec §4.1 fixes the supported set:
 *  paragraph, H1/H2/H3, bullet list, numbered list, quote, code block, divider,
 *  link. Nothing else.
 */
import type { JSONContent } from '@tiptap/react'
import type { Block } from './api'

export type DraftBlock = { id?: number | null; position: number; block_type: string; text: string }

/** Flatten a Tiptap doc into a positional block list. */
export function docToBlocks(doc: JSONContent): Array<{ block_type: string; text: string }> {
  const out: Array<{ block_type: string; text: string }> = []

  for (const node of doc.content ?? []) {
    switch (node.type) {
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
        out.push({ block_type: 'code_block', text: textOf(node) })
        break
      case 'horizontalRule':
        out.push({ block_type: 'divider', text: '' })
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
        content.push({ type: 'codeBlock', content: inline(block.text) })
        break
      case 'divider':
        content.push({ type: 'horizontalRule' })
        break
      default:
        content.push(paragraph(block.text))
    }
    i++
  }

  if (content.length === 0) content.push(paragraph(''))
  return { type: 'doc', content }
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
  serialised: Array<{ block_type: string; text: string }>,
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
  }))
}
