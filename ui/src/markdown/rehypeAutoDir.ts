/** Set per-block dir="auto" so alignment and list markers follow the text.
 * CSS bidi ordering alone does not set direction. Leave code in LTR order. */
import type { Root, Element } from 'hast';

/** Block elements whose text is prose, so direction should follow content. */
const AUTO_DIR = new Set([
  'p', 'li', 'blockquote', 'td', 'th', 'dd', 'dt', 'figcaption', 'summary',
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  // Lists need container direction for bullet placement. Keep table column order unchanged.
  'ul', 'ol'
]);

/** Subtrees to leave strictly LTR (code keeps its own order). */
const SKIP = new Set(['pre', 'code']);

export function rehypeAutoDir() {
  return (tree: Root): void => {
    const walk = (node: Root | Element): void => {
      for (const child of node.children) {
        if (child.type !== 'element') continue;
        if (SKIP.has(child.tagName)) continue;
        if (AUTO_DIR.has(child.tagName)) {
          child.properties = { ...child.properties, dir: 'auto' };
        }
        walk(child);
      }
    };
    walk(tree);
  };
}
