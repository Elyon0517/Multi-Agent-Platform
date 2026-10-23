import { useEffect, useState } from 'react';
export function useTypewriter(text: string, seed: unknown, cps = 90): { shown: string; done: boolean } {
  const [length, setLength] = useState(0);
  useEffect(() => {
    setLength(0);
    const characters = Math.max(1, Number.isFinite(cps) ? cps : 90);
    const began = performance.now();
    let animation = 0;
    const advance = () => {
      const count = Math.min(text.length, Math.floor((performance.now() - began) * characters / 1000));
      setLength(count);
      if (count < text.length) animation = requestAnimationFrame(advance);
    };
    if (text) animation = requestAnimationFrame(advance);
    return () => cancelAnimationFrame(animation);
  }, [text, seed, cps]);
  return { shown: text.slice(0, length), done: length >= text.length };
}
