/** Shared document and card preview. Keep raw HTML disabled for untrusted markdown.
 * External links use the bridge; relative markdown links use onOpenMarkdownLink. */
import { memo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useWorkspaceImage } from '@/hooks/useWorkspaceImage';
import { isExternal, isRelativeMd, resolveLocalImageRel, resolveRel } from './mdLinks';
import { remarkSoftBreaks } from './remarkSoftBreaks';
import { rehypeAutoDir } from './rehypeAutoDir';
import { useRtl } from '@/i18n/useDirection';

/** Documents use page styling; cards inherit host styling and preserve newlines. */
export type MarkdownVariant = 'document' | 'card';

// Hoisted: a fresh array on every render would make react-markdown re-run the
// whole pipeline even when nothing about the source changed.
const DOC_PLUGINS = [remarkGfm];
const CARD_PLUGINS = [remarkGfm, remarkSoftBreaks];

/** Per-block `dir="auto"`, for an RTL app language only — see the note at the
 *  `useRtl()` call site below. Frozen module constants so the prop identity is
 *  stable and react-markdown does not re-run the pipeline on every render. */
const AUTO_DIR_PLUGINS = [rehypeAutoDir];
const NO_PLUGINS: never[] = [];

export interface MarkdownPreviewProps {
  source: string;
  /** Repo-relative path of the file being previewed (for resolving relative links). */
  baseRel?: string;
  /** Registered project ID; image reads are confined to that project's workspace. */
  projectId?: string;
  /** Open a sibling markdown file (repo-relative path) in the host's context. */
  onOpenMarkdownLink?: (rel: string) => void;
  /** Page vs in-card rendering. Defaults to `document`. */
  variant?: MarkdownVariant;
}

export const MarkdownPreview = memo(function MarkdownPreview({
  source, baseRel, projectId, onOpenMarkdownLink, variant = 'document'
}: MarkdownPreviewProps) {
  const card = variant === 'card';
  // Enable per-block direction only when the selected app language is RTL.
  const rtl = useRtl();
  return (
    <div className={card ? 'cth-md-preview cth-md-card' : 'cth-md-preview'}>
      <ReactMarkdown
        remarkPlugins={card ? CARD_PLUGINS : DOC_PLUGINS}
        rehypePlugins={rtl ? AUTO_DIR_PLUGINS : NO_PLUGINS}
        components={{
          a: ({ href, children }) => {
            const h = href ?? '';
            const onClick = (e: React.MouseEvent) => {
              e.preventDefault();
              if (isExternal(h)) { void window.cth.openExternal?.(h); return; }
              if (isRelativeMd(h) && onOpenMarkdownLink) {
                onOpenMarkdownLink(resolveRel(baseRel, h.replace(/#.*$/, '')));
              }
              // anything else (file:, anchors into self, unknown schemes): inert
            };
            const clickable = isExternal(h) || (isRelativeMd(h) && !!onOpenMarkdownLink);
            return (
              <a
                href={h || undefined}
                onClick={onClick}
                title={h}
                style={clickable ? undefined : { cursor: 'default', textDecoration: 'underline dotted' }}
              >
                {children}
              </a>
            );
          },
          // Local images load through the workspace bridge; remote images use placeholders.
          img: ({ alt, src }) => {
            const s = typeof src === 'string' ? src : undefined;
            const rel = projectId ? resolveLocalImageRel(baseRel, s) : null;
            if (!projectId || !rel) return <ImageChip alt={alt} src={s} />;
            return <MdImage key={`${projectId}:${rel}`} projectId={projectId} rel={rel} alt={alt} src={s} />;
          }
        }}
      >
        {source}
      </ReactMarkdown>
    </div>
  );
});

/** Fallback for anything we won't (or can't) load: remote URLs, non-images,
 *  and local files that turned out to be missing or undecodable. */
function ImageChip({ alt, src, note }: { alt?: string; src?: string; note?: string }) {
  return (
    <span className="cth-md-img" title={src}>
      🖼 {alt || 'image'}{note ? ` — ${note}` : ''}
    </span>
  );
}

/** A local image inside rendered markdown. Falls back to the chip on any
 *  failure so a stale path in a report degrades to the old behaviour instead of
 *  a broken-image glyph. Blob lifetime (create AND revoke) belongs to the hook. */
function MdImage({ projectId, rel, alt, src }: { projectId: string; rel: string; alt?: string; src?: string }) {
  const img = useWorkspaceImage(projectId, rel);
  const [decodeFailed, setDecodeFailed] = useState(false);
  if (img.status === 'loading') return <ImageChip alt={alt} src={src} note="loading" />;
  if (img.status === 'error') return <ImageChip alt={alt} src={src} note={img.error} />;
  if (decodeFailed) return <ImageChip alt={alt} src={src} note="could not decode" />;
  return (
    <img
      className="cth-md-image"
      src={img.url}
      alt={alt || rel}
      title={src}
      onError={() => setDecodeFailed(true)}
    />
  );
}
