import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import { resolveGodName, DEFAULT_GOD_NAME } from '@/shared/godIdentity';
import en from './locales/en.json';
import zh from './locales/zh-CN.json';
export type LanguageCode = 'en' | 'zh-CN';
export const LANGUAGES: ReadonlyArray<{ code: LanguageCode; label: string; dir: 'ltr' | 'rtl' }> = [
  { code: 'en', label: 'English', dir: 'ltr' }, { code: 'zh-CN', label: '简体中文', dir: 'ltr' },
];
export function directionFor(code: string | null | undefined): 'ltr' | 'rtl' {
  return LANGUAGES.find(language => language.code === code)?.dir ?? 'ltr';
}
export function isRtlLanguage(code: string | null | undefined): boolean { return directionFor(code) === 'rtl'; }
function savedLanguage(): string {
  try { const code = localStorage.getItem('cth.language'); return LANGUAGES.find(l => l.code === code)?.code ?? 'en'; }
  catch { return 'en'; }
}
export function setLanguage(code: string): void {
  if (!LANGUAGES.some(l => l.code === code)) return;
  void i18n.changeLanguage(code);
  try { localStorage.setItem('cth.language', code); } catch { /* Storage is optional. */ }
}
export function setGodName(name: string | null | undefined): void {
  const options = i18n.options.interpolation ??= {};
  const variables = options.defaultVariables ??= {};
  const resolved = resolveGodName(name);
  if (variables.godName !== resolved) { variables.godName = resolved; i18n.emit('languageChanged', i18n.language); }
}
void i18n.use(initReactI18next).init({ resources: { en: { translation: en }, 'zh-CN': { translation: zh } },
  lng: savedLanguage(), fallbackLng: 'en', supportedLngs: LANGUAGES.map(l => l.code), returnNull: false,
  react: { useSuspense: false }, interpolation: { escapeValue: false, defaultVariables: { godName: DEFAULT_GOD_NAME } } });
i18n.on('languageChanged', code => {
  document.documentElement.setAttribute('lang', code); document.documentElement.setAttribute('dir', directionFor(code));
});
document.documentElement.lang = i18n.language;
document.documentElement.dir = directionFor(i18n.language);
export default i18n;
