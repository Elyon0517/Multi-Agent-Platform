import { useEffect, useRef } from 'react';
import { paintCastPortrait, type OfficeCharacterName } from '@/scene/office/cast';
import { PORTRAIT_W, PORTRAIT_H } from '@/scene/office/portraitArt';
export interface SpritePortraitProps { character: OfficeCharacterName; scale?: number; background?: string; }
export function SpritePortrait({ character, scale = 2, background = 'transparent' }: SpritePortraitProps) {
  const ref = useRef<HTMLCanvasElement>(null);
  const width = Math.round(PORTRAIT_W * scale), height = Math.round(PORTRAIT_H * scale);
  useEffect(() => {
    const context = ref.current?.getContext('2d');
    if (!context) return;
    context.clearRect(0, 0, width, height);
    void paintCastPortrait(context, character, scale);
  }, [character, scale, width, height]);
  return <canvas ref={ref} width={width} height={height} role="img" aria-label={character}
    style={{ width, height, imageRendering: 'pixelated', background }} />;
}
