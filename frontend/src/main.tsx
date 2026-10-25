import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import './lib/pdfWorker'
import App from './App.tsx'
import { Toaster } from '@/components/ui/sonner'
import { AssistantProvider } from '@/components/assistant/Assistant'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AssistantProvider>
          <App />
        </AssistantProvider>
        <Toaster />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
