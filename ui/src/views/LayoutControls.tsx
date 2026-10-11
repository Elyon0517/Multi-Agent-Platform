import { useTranslation } from 'react-i18next';
import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';
import { OfficeFloor } from '@/scene/office/OfficeFloor';
import { Icon } from '@/components/Icon';
import { PixelButton } from '@/components/PixelButton';
import { DEFAULT_CONSOLE_WIDTH, MIN_CONSOLE_WIDTH, MIN_MAIN_WIDTH } from './layoutPrefs';

const STEP = 24;

/** Draggable divider between the office and the console. Arrow keys resize, double-click resets. */
export function ConsoleSplitter({ width, leftWidth, onChange }: {
  width: number; leftWidth: number; onChange: (width: number) => void;
}) {
  const { t } = useTranslation();
  const dragging = useRef(false);
  const max = Math.max(MIN_CONSOLE_WIDTH, window.innerWidth - leftWidth - MIN_MAIN_WIDTH);
  const clamp = (value: number) => Math.round(Math.min(max, Math.max(MIN_CONSOLE_WIDTH, value)));

  const move = (e: PointerEvent<HTMLDivElement>) => {
    // The console is the last column, so its width is the distance from the pointer to the right edge.
    if (dragging.current) onChange(clamp(window.innerWidth - e.clientX - 8));
  };
  const key = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'ArrowLeft') { e.preventDefault(); onChange(clamp(width + STEP)); }
    if (e.key === 'ArrowRight') { e.preventDefault(); onChange(clamp(width - STEP)); }
  };
  return (
    <div className="console-splitter" role="separator" aria-orientation="vertical" tabIndex={0}
      aria-label={t('lab.resizeConsole')} aria-valuemin={MIN_CONSOLE_WIDTH} aria-valuemax={max} aria-valuenow={width}
      title={t('lab.resizeConsole')}
      onPointerDown={(e) => { dragging.current = true; e.currentTarget.setPointerCapture(e.pointerId); }}
      onPointerMove={move}
      onPointerUp={(e) => { dragging.current = false; e.currentTarget.releasePointerCapture(e.pointerId); }}
      onDoubleClick={() => onChange(clamp(DEFAULT_CONSOLE_WIDTH))}
      onKeyDown={key} />
  );
}

/** The office is a monitor of agent activity: it can fill the screen or shrink to a bar.
 *  Minimized, the Pixi scene is unmounted so it stops rendering entirely. */
export function OfficeMonitor({ minimized, onMinimizedChange }: {
  minimized: boolean; onMinimizedChange: (minimized: boolean) => void;
}) {
  const { t } = useTranslation();
  const ref = useRef<HTMLElement>(null);
  const [fullscreen, setFullscreen] = useState(false);
  useEffect(() => {
    const sync = () => setFullscreen(document.fullscreenElement === ref.current);
    document.addEventListener('fullscreenchange', sync);
    return () => document.removeEventListener('fullscreenchange', sync);
  }, []);

  if (minimized) {
    return (
      <section aria-label={t('lab.officeFloor')} className="office-minimized">
        <span>{t('lab.officeMinimized')}</span>
        <PixelButton size="sm" variant="secondary" onClick={() => onMinimizedChange(false)}>{t('lab.officeRestore')}</PixelButton>
      </section>
    );
  }
  const toggleFullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void ref.current?.requestFullscreen();
  };
  return (
    <section ref={ref} aria-label={t('lab.officeFloor')} style={{ position: 'relative', minHeight: 0, background: 'var(--cth-ink-900)' }}>
      <OfficeFloor />
      <div className="office-controls">
        <button type="button" onClick={toggleFullscreen}
          title={t(fullscreen ? 'lab.officeExitFullscreen' : 'lab.officeFullscreen')}
          aria-label={t(fullscreen ? 'lab.officeExitFullscreen' : 'lab.officeFullscreen')}>
          <Icon name={fullscreen ? 'minimize' : 'expand'} />
        </button>
        {!fullscreen && (
          <button type="button" onClick={() => onMinimizedChange(true)} title={t('lab.officeMinimize')} aria-label={t('lab.officeMinimize')}>
            <span aria-hidden style={{ display: 'inline-block', width: 16, textAlign: 'center', fontWeight: 700 }}>—</span>
          </button>
        )}
      </div>
    </section>
  );
}
