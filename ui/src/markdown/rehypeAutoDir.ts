import type { Root, Element } from 'hast';
export function rehypeAutoDir() {
  return (root: Root): void => {
    const pending: (Root | Element)[] = [root];
    while (pending.length) {
      for (const node of pending.pop()!.children) {
        if (node.type !== 'element' || /^(pre|code)$/.test(node.tagName)) continue;
        if (/^(p|li|blockquote|td|th|dd|dt|figcaption|summary|h[1-6]|ul|ol)$/.test(node.tagName))
          node.properties.dir = 'auto';
        pending.push(node);
      }
    }
  };
}
