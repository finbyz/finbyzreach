import { createRoot } from 'react-dom/client'
import { FrappeProvider } from 'frappe-react-sdk'

import App from './App'
import { NotificationProvider } from './components/notifications'
import './index.css'

const frappeBoot = (window as unknown as { frappe?: { boot?: { sitename?: string } } }).frappe?.boot

const swrConfig = {
  dedupingInterval: 10_000,
  revalidateOnFocus: false,
  shouldRetryOnError: false,
}

createRoot(document.getElementById('root')!).render(
  <FrappeProvider swrConfig={swrConfig} enableSocket={true} siteName={frappeBoot?.sitename}>
    <NotificationProvider>
      <App />
    </NotificationProvider>
  </FrappeProvider>,
)
