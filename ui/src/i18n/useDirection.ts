import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { directionFor } from './index';
export function useRtl(): boolean { return directionFor(useTranslation().i18n.language) === 'rtl'; }
export function useDirectionSync(): void {
  const { i18n } = useTranslation();
  useEffect(() => {
    document.documentElement.lang = i18n.language || 'en';
    document.documentElement.dir = directionFor(i18n.language);
  }, [i18n.language]);
}
