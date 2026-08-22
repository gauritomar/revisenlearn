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
