import { MutationCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { reportError } from './components/errors'
import './styles.css'

const client = new QueryClient({
  // A failed mutation nobody handled itself is shown to the user instead of being swallowed.
  mutationCache: new MutationCache({ onError: (error, _v, _c, mutation) => { if (!mutation.options.onError) reportError(error) } }),
  defaultOptions: { queries: { staleTime: 10_000, refetchOnWindowFocus: true, retry: 1 } },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
