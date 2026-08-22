import { Extension, InputRule } from '@tiptap/core'

/** Consolidated addendum §2 — "Typing `- [ ] text` creates one; `- [x] text`
 *  creates it pre-checked."
 *
 *  That exact sequence needs help. StarterKit turns `- ` into a bullet the
 *  moment the space lands, so by the time `[ ] ` is typed the cursor is inside
 *  a `listItem`, where TaskItem's own rule cannot wrap anything: a `taskItem`
 *  may only live in a `taskList`. This rule fires at that second stage and
 *  converts the list itself, which also gives the bare `[ ] ` form (no dash)
 *  for free.
 */
const CHECKBOX = /^\s*\[([ xX]?)\]\s$/

export const CheckboxInput = Extension.create({
  name: 'checkboxInput',

  addInputRules() {
    return [
      new InputRule({
        find: CHECKBOX,
        handler: ({ range, match, chain }) => {
          const checked = match[1].toLowerCase() === 'x'
          chain()
            .deleteRange(range)
            .toggleList('taskList', 'taskItem')
            .updateAttributes('taskItem', { checked })
            .run()
        },
      }),
    ]
  },
})


/** ``` and ```python, from anywhere — including inside a list.
 *
 *  The built-in fence rule only fires in a plain paragraph, so a note that is
 *  mostly bullets (which is most notes here) cannot start a code block
 *  without first leaving the list by hand. Typing three backticks is an
 *  unambiguous instruction; this honours it wherever the cursor is.
 */
const FENCE = /^```([a-zA-Z0-9+#_-]*)[\s]$/

export const CodeFenceAnywhere = Extension.create({
  name: 'codeFenceAnywhere',

  addInputRules() {
    return [
      new InputRule({
        find: FENCE,
        handler: ({ range, match, chain, state }) => {
          const language = (match[1] || 'plaintext').toLowerCase()

          // Are we inside a list item? Only then is lifting needed — calling
          // it unconditionally would fail the chain in a plain paragraph.
          let inList = false
          const { $from } = state.selection
          for (let depth = $from.depth; depth > 0; depth--) {
            const name = $from.node(depth).type.name
            if (name === 'listItem' || name === 'taskItem') {
              inList = true
              break
            }
          }

          const run = chain().deleteRange(range)
          if (inList) run.liftListItem('listItem')
          run.setNode('codeBlock', { language }).run()
        },
      }),
    ]
  },
})
