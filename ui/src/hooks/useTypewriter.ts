import { useEffect, useState } from 'react';

/** Reveal text at cps characters per second; changing seed restarts the animation. */
export function useTypewriter(text: string, seed: unknown, cps = 90): {
  shown: string;
  done: boolean;
} {
  const [shown, setShown] = useState('');
  const [done, setDone] = useState(false);

  useEffect(() => {
    setShown('');
    setDone(false);
    if (!text) { setDone(true); return; }
    let i = 0;
    const intervalMs = Math.max(8, Math.floor(1000 / cps));
    const id = window.setInterval(() => {
      i++;
      setShown(text.slice(0, i));
      if (i >= text.length) {
        window.clearInterval(id);
        setDone(true);
      }
    }, intervalMs);
    return () => window.clearInterval(id);
  }, [text, seed, cps]);

  return { shown, done };
}
