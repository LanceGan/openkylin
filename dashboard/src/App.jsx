import { useState } from 'react'
import BootTimeline from './components/BootTimeline.jsx'
import Optimization from './components/Optimization.jsx'
import AgentDashboard from './components/AgentDashboard.jsx'

const TABS = [
  { id: 'timeline', label: 'Boot Timeline' },
  { id: 'optimization', label: 'Optimization' },
  { id: 'agent', label: 'Agent' },
]

function App() {
  const [activeTab, setActiveTab] = useState('timeline')

  const renderContent = () => {
    switch (activeTab) {
      case 'timeline':
        return <BootTimeline />
      case 'optimization':
        return <Optimization />
      case 'agent':
        return <AgentDashboard />
      default:
        return null
    }
  }

  return (
    <div className="min-h-screen" style={{ backgroundColor: '#f4f5f2', color: '#1d2421' }}>
      {/* Title bar */}
      <header className="border-b px-6 py-4" style={{ borderColor: '#d1d3cf' }}>
        <h1 className="text-2xl font-bold tracking-tight" style={{ color: '#1d2421' }}>
          KylinBootLab
        </h1>
        <p className="text-sm mt-1" style={{ color: '#52605a' }}>
          openKylin Boot Performance Analysis
        </p>
      </header>

      {/* Tab bar */}
      <nav className="flex border-b px-6" style={{ borderColor: '#d1d3cf' }}>
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActiveTab(tab.id)}
            className="px-5 py-3 text-sm font-medium transition-colors cursor-pointer border-b-2"
            style={{
              color: activeTab === tab.id ? '#2a78d6' : '#52605a',
              borderBottomColor: activeTab === tab.id ? '#2a78d6' : 'transparent',
              marginBottom: '-1px',
            }}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {/* Content area */}
      <main className="max-w-6xl mx-auto px-6 py-8">
        {renderContent()}
      </main>
    </div>
  )
}

export default App
