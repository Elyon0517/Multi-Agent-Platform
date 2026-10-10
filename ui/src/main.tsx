import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { installBridge } from '@/bridge';
import '@/i18n';
import '@/design/fonts.css';
import '@/design/tokens.css';
import '@/design/global.css';
import { App } from '@/App';

installBridge();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
