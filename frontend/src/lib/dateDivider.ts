import { Node, mergeAttributes } from '@tiptap/core'

/** Consolidated addendum §3 — "When the first edit of a new calendar day
 *  happens on an existing lesson note, insert a lightweight date-divider block
 *  automatically, so a note spanning months stays navigable."
 *
 *  The backend writes these, never the user, so the node is atomic and not
 *  editable: it round-trips through the editor untouched, and cannot be half
 *  deleted into a paragraph that says "2026-08-22".
 */
export const DateDivider = Node.create({
  name: 'dateDivider',
  group: 'block',
  atom: true,
  selectable: true,
  draggable: false,

  addAttributes() {
    return {
      date: {
        default: '',
        parseHTML: (element) => element.getAttribute('data-date') ?? '',
        renderHTML: (attributes) => ({ 'data-date': attributes.date }),
      },
    }
  },

  parseHTML() {
    return [{ tag: 'div[data-date-divider]' }]
  },

  renderHTML({ HTMLAttributes, node }) {
    const raw = String(node.attrs.date ?? '')
    // A long note is read by skimming: show the day, not the ISO string.
    let label = raw
    const parts = /^(\d{4})-(\d{2})-(\d{2})$/.exec(raw)
    if (parts) {
      const date = new Date(Number(parts[1]), Number(parts[2]) - 1, Number(parts[3]))
      label = date.toLocaleDateString(undefined, {
        weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
      })
    }
    return [
      'div',
      mergeAttributes(HTMLAttributes, {
        'data-date-divider': '',
        'data-testid': 'date-divider',
        class: 'date-divider',
      }),
      ['span', {}, label],
    ]
  },
})
