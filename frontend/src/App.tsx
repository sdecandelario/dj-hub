import { useQuery } from '@tanstack/react-query'
import { NavLink, Route, Routes } from 'react-router-dom'
import { api, type Summary } from './api'
import { BatchProvider } from './components/batch'
import { ErrorToasts } from './components/errors'
import { JobBar, JobsProvider } from './components/jobs'
import Analysis from './pages/Analysis'
import Discover from './pages/Discover'
import Downloads from './pages/Downloads'
import History from './pages/History'
import Home from './pages/Home'
import Library from './pages/Library'
import Playlists from './pages/Playlists'
import SettingsPage from './pages/Settings'

function Nav() {
  const { data } = useQuery({ queryKey: ['summary'], queryFn: () => api.get<Summary>('/summary') })
  const links: [string, string, number | undefined][] = [
    ['/', 'Home', undefined],
    ['/playlists', 'Playlists', data?.missing],
    ['/discover', 'Discover', undefined],
    ['/downloads', 'Downloads', data?.review_pending],
    ['/library', 'Library', data?.inbox],
    ['/analysis', 'Analysis', undefined],
    ['/history', 'History', undefined],
    ['/settings', 'Settings', undefined],
  ]
  return (
    <nav className="sidebar">
      <div className="brand"><img src="/favicon.svg" width={22} height={22} alt="" /> DJ Hub</div>
      <div className="nav">
        {links.map(([to, label, count]) => (
          <NavLink key={to} to={to} end={to === '/'}>
            {label}
            {count ? <span className="count">{count}</span> : null}
          </NavLink>
        ))}
      </div>
    </nav>
  )
}

export default function App() {
  return (
    <JobsProvider>
      <BatchProvider>
        <div className="app">
          <Nav />
          <main className="main">
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/playlists" element={<Playlists />} />
              <Route path="/discover" element={<Discover />} />
              <Route path="/downloads" element={<Downloads />} />
              <Route path="/library" element={<Library />} />
              <Route path="/analysis" element={<Analysis />} />
              <Route path="/history" element={<History />} />
              <Route path="/settings" element={<SettingsPage />} />
            </Routes>
          </main>
        </div>
        <JobBar />
        <ErrorToasts />
      </BatchProvider>
    </JobsProvider>
  )
}
