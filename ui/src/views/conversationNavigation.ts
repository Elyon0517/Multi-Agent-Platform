import type { Conversation } from '@/api/client';
export function hasConversationContent(thread: Conversation): boolean {
  return thread.messages.some(message => message.text.trim().length > 0);
}
export function conversationTitle(thread: Conversation): string {
  const first = thread.messages.find(message => message.author === 'user' && message.text.trim());
  const generic = /^(new conversation|新对话|新建对话)$/i.test(thread.title.trim());
  return (generic && first ? first.text : thread.title).replace(/\s+/g, ' ').trim().slice(0, 60);
}
