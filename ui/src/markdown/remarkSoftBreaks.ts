/** Preserve message newlines in card previews; leave code nodes unchanged. */

interface MdNode {
  type: string;
  value?: string;
  children?: MdNode[];
}

function walk(node: MdNode): void {
  const children = node.children;
  if (!children) return;
  const out: MdNode[] = [];
  for (const child of children) {
    if (child.type === 'text' && typeof child.value === 'string' && child.value.includes('\n')) {
      const parts = child.value.split('\n');
      for (let i = 0; i < parts.length; i++) {
        if (i > 0) out.push({ type: 'break' });
        if (parts[i]) out.push({ type: 'text', value: parts[i] });
      }
      continue;
    }
    walk(child);
    out.push(child);
  }
  node.children = out;
}

export function remarkSoftBreaks() {
  return (tree: unknown): void => { walk(tree as MdNode); };
}
