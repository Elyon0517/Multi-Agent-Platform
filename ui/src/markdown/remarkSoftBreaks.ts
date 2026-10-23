interface Node { type: string; value?: string; children?: Node[]; }
export function remarkSoftBreaks() {
  return (root: unknown): void => {
    const pending = [root as Node];
    while (pending.length) {
      const parent = pending.pop()!;
      if (!parent.children || parent.type === 'code' || parent.type === 'inlineCode') continue;
      parent.children = parent.children.flatMap(child => {
        pending.push(child);
        if (child.type !== 'text' || !child.value?.includes('\n')) return [child];
        return child.value.split('\n').flatMap((value, index): Node[] => [
          ...(index ? [{ type: 'break' }] : []), ...(value ? [{ type: 'text', value }] : []),
        ]);
      });
    }
  };
}
