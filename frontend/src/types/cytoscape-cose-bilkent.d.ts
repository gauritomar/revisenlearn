/** `cytoscape-cose-bilkent` ships no type declarations. It is a plain
 *  Cytoscape extension: a function handed to `cytoscape.use`. */
declare module 'cytoscape-cose-bilkent' {
  import type { Ext } from 'cytoscape'
  const extension: Ext
  export default extension
}
