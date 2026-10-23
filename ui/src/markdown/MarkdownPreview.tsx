import { memo, useState, type MouseEvent } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useWorkspaceImage } from '@/hooks/useWorkspaceImage';
import { useRtl } from '@/i18n/useDirection';
import { resolveLocalImageRel, resolveRel, isExternal, isRelativeMd } from './mdLinks';
import { remarkSoftBreaks } from './remarkSoftBreaks';
import { rehypeAutoDir } from './rehypeAutoDir';
export type MarkdownVariant = 'document' | 'card';
export interface MarkdownPreviewProps {
  source: string; baseRel?: string; projectId?: string; onOpenMarkdownLink?: (relative: string) => void; variant?: MarkdownVariant;
}
const documentRules = [remarkGfm], cardRules = [remarkGfm, remarkSoftBreaks], directionRules = [rehypeAutoDir];
function Placeholder({ title, description }: { title?: string; description: string }) {
  return <span className="cth-md-img" title={title}>🖼 {description}</span>;
}
function ProjectImage({ project, path, description, title }: { project: string; path: string; description?: string; title?: string }) {
  const result = useWorkspaceImage(project, path), [invalid, setInvalid] = useState(false);
  if (result.status !== 'ready' || invalid) return <Placeholder title={title}
    description={`${description || 'image'} — ${invalid ? 'could not decode' : result.status === 'error' ? result.error : 'loading'}`} />;
  return <img className="cth-md-image" src={result.url} alt={description || path} title={title} onError={() => setInvalid(true)} />;
}
export const MarkdownPreview = memo(function MarkdownPreview(props: MarkdownPreviewProps) {
  const rtl = useRtl(), card = props.variant === 'card';
  return <div className={`cth-md-preview${card ? ' cth-md-card' : ''}`}>
    <ReactMarkdown skipHtml remarkPlugins={card ? cardRules : documentRules} rehypePlugins={rtl ? directionRules : []}
      components={{
        a: ({ href = '', children }) => {
          const external = isExternal(href), document = isRelativeMd(href) && !!props.onOpenMarkdownLink;
          const follow = (event: MouseEvent) => {
            event.preventDefault();
            if (external) void window.cth.openExternal(href);
            else if (document) props.onOpenMarkdownLink?.(resolveRel(props.baseRel, href.replace(/#.*$/, '')));
          };
          return <a href={external || document ? href : undefined} title={href} onClick={follow}
            style={external || document ? undefined : { cursor: 'default', textDecoration: 'underline dotted' }}>{children}</a>;
        },
        img: ({ src, alt }) => {
          const path = props.projectId ? resolveLocalImageRel(props.baseRel, src) : null;
          return path && props.projectId ? <ProjectImage key={`${props.projectId}/${path}`} project={props.projectId}
            path={path} description={alt} title={src} /> : <Placeholder title={src} description={alt || 'image'} />;
        },
      }}>{props.source}</ReactMarkdown>
  </div>;
});
