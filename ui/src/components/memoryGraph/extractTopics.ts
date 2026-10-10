// Topic extraction for the memory graph — pure, dependency-free, client-side.
//
// Agent memory.md files are structured markdown: dated `## <date> — <title>`
// section headers, `**bold**` key terms, bullet lists. We pull candidate topic
// phrases from headings + bold spans, normalise them, and keep only the ones
// mentioned by >= 2 distinct agents (shared knowledge is the interesting signal;
// an agent's solo notes aren't a hive-wide "topic"). See MEMORY_GRAPH_SPEC.md §5.
//
// This is deliberately heuristic, not semantic — MemPalace (searchMemory) owns
// the semantic side and returns ranked snippets per query, not an enumerable set.

export interface Topic {
  /** stable node id, e.g. "topic:landing page redesign" */
  id: string;
  /** human-facing label (first-seen original casing) */
  label: string;
  /** ids of agents whose memory mentions this topic */
  agentIds: string[];
  /** = agentIds.length; how many agents share it */
  weight: number;
}

export interface TopicResult {
  /** topics sorted by weight desc, then label — already capped to `max` */
  topics: Topic[];
  /** total number of qualifying topics (weight >= 2) before the cap */
  total: number;
}

// Generic words/phrases that show up as headings or bold but aren't real topics.
const STOP = new Set([
  'update', 'updates', 'done', 'note', 'notes', 'next', 'open', 'todo', 'todos',
  'fixed', 'resolved', 'wip', 'status', 'context', 'memory', 'summary', 'decision',
  'decisions', 'plan', 'plans', 'task', 'tasks', 'phase 1', 'phase 2', 'phase',
  'why', 'how', 'what', 'gap', 'gaps', 'needed', 'open / next', 'important', 'fact', 'facts'
]);

/** Strip a leading `YYYY-MM-DD —`/`-`/`:` date prefix from a heading tail. */
function stripDatePrefix(s: string): string {
  return s.replace(/^\s*\d{4}-\d{2}-\d{2}\s*[—\-:·]*\s*/, '');
}

/** Lowercase, collapse whitespace, drop surrounding markup/punctuation. */
function normalise(raw: string): string {
  return raw
    .replace(/[`*_~]/g, '')           // strip inline md markup
    .replace(/\(.*?\)/g, '')          // drop parentheticals
    .replace(/[#:.,;!?]+$/g, '')      // trailing punctuation
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
}

/** Pull raw candidate phrases out of one memory file's markdown. */
function candidatesFrom(markdown: string): string[] {
  const out: string[] = [];
  for (const line of markdown.split('\n')) {
    const heading = line.match(/^#{2,4}\s+(.+?)\s*$/);
    if (heading) out.push(stripDatePrefix(heading[1]));
    for (const m of line.matchAll(/\*\*(.+?)\*\*/g)) out.push(stripDatePrefix(m[1]));
  }
  return out;
}

function isUsable(norm: string): boolean {
  if (norm.length < 3 || norm.length > 40) return false;
  if (STOP.has(norm)) return false;
  if (/^[\d\s\-—.]+$/.test(norm)) return false;   // pure numbers/dates
  if (!/[a-z]/.test(norm)) return false;          // must contain letters
  return true;
}

/**
 * Build the shared-topic set across all agents' memory files.
 * @param memories agentId -> raw memory.md text
 * @param max      cap on returned topics (default 24, per spec)
 */
export function extractTopics(memories: Record<string, string>, max = 24): TopicResult {
  // normalised topic -> { display label, set of agent ids }
  const acc = new Map<string, { label: string; agents: Set<string> }>();

  for (const [agentId, text] of Object.entries(memories)) {
    if (!text) continue;
    const seenThisAgent = new Set<string>();
    for (const cand of candidatesFrom(text)) {
      const norm = normalise(cand);
      if (!isUsable(norm) || seenThisAgent.has(norm)) continue;
      seenThisAgent.add(norm);
      const entry = acc.get(norm);
      if (entry) entry.agents.add(agentId);
      else acc.set(norm, { label: cand.replace(/[`*_]/g, '').trim(), agents: new Set([agentId]) });
    }
  }

  const all: Topic[] = [];
  for (const [norm, { label, agents }] of acc) {
    if (agents.size < 2) continue;
    all.push({ id: `topic:${norm}`, label, agentIds: [...agents], weight: agents.size });
  }
  all.sort((a, b) => b.weight - a.weight || a.label.localeCompare(b.label));

  return { topics: all.slice(0, max), total: all.length };
}
