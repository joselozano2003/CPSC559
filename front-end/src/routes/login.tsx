import { createFileRoute, useRouter } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { Button } from '#/components/ui/button'
import { Input } from '#/components/ui/input'
import { Label } from '#/components/ui/label'
import { apiLogin, getRefreshToken, setMasterUrl, setTokens } from '#/lib/api'

export const Route = createFileRoute('/login')({ component: LoginPage })

function LoginPage() {
  const router = useRouter()
  const [masterUrl, setMasterUrlState] = useState('http://localhost')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (getRefreshToken()) router.navigate({ to: '/' })
  }, [])

  async function handleLogin() {
    if (!masterUrl || !email || !password) {
      setError('Please fill in all fields.')
      return
    }
    setLoading(true)
    setError('')
    try {
      const data = await apiLogin(email, password, masterUrl)
      setTokens(data.tokens.access, data.tokens.refresh)
      setMasterUrl(masterUrl)
      router.navigate({ to: '/' })
    } catch (e: any) {
      setError(e.message || 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex">

      {/* Left panel */}
      <div className="login-blue-panel hidden lg:flex lg:w-[44%] relative overflow-hidden flex-col justify-between p-12">

        {/* Grid overlay */}
        <div
          className="absolute inset-0"
          style={{
            backgroundImage:
              'linear-gradient(rgba(255,255,255,0.06) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.06) 1px, transparent 1px)',
            backgroundSize: '40px 40px',
          }}
        />

        {/* Decorative node graph */}
        <div className="absolute inset-0 flex items-center justify-center opacity-[0.12] pointer-events-none">
          <svg width="520" height="520" viewBox="0 0 520 520" fill="none">
            <line x1="260" y1="90"  x2="90"  y2="220" stroke="white" strokeWidth="1.2"/>
            <line x1="260" y1="90"  x2="430" y2="220" stroke="white" strokeWidth="1.2"/>
            <line x1="260" y1="90"  x2="260" y2="330" stroke="white" strokeWidth="1.2"/>
            <line x1="90"  y1="220" x2="430" y2="220" stroke="white" strokeWidth="1.2"/>
            <line x1="90"  y1="220" x2="140" y2="400" stroke="white" strokeWidth="1.2"/>
            <line x1="430" y1="220" x2="380" y2="400" stroke="white" strokeWidth="1.2"/>
            <line x1="140" y1="400" x2="380" y2="400" stroke="white" strokeWidth="1.2"/>
            <line x1="260" y1="330" x2="140" y2="400" stroke="white" strokeWidth="1.2"/>
            <line x1="260" y1="330" x2="380" y2="400" stroke="white" strokeWidth="1.2"/>
            <line x1="90"  y1="220" x2="260" y2="330" stroke="white" strokeWidth="0.8" strokeDasharray="4 4"/>
            <line x1="430" y1="220" x2="260" y2="330" stroke="white" strokeWidth="0.8" strokeDasharray="4 4"/>
            <circle cx="260" cy="90"  r="14" fill="white" fillOpacity="0.9"/>
            <circle cx="90"  cy="220" r="11" fill="white" fillOpacity="0.7"/>
            <circle cx="430" cy="220" r="11" fill="white" fillOpacity="0.7"/>
            <circle cx="260" cy="330" r="11" fill="white" fillOpacity="0.7"/>
            <circle cx="140" cy="400" r="9"  fill="white" fillOpacity="0.5"/>
            <circle cx="380" cy="400" r="9"  fill="white" fillOpacity="0.5"/>
            <circle cx="260" cy="90"  r="6"  fill="#60A5FA" fillOpacity="0.9"/>
          </svg>
        </div>

        {/* Top: Logo */}
        <div className="relative z-10">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl flex items-center justify-center border border-white/20 bg-white/10">
              <NodeIcon size={18} />
            </div>
            <span className="text-white/80 text-xs font-semibold tracking-[0.2em] uppercase">DFS</span>
          </div>
        </div>

        {/* Center: Headline */}
        <div className="relative z-10">
          <h1
            className="text-[3.2rem] font-bold text-white leading-[1.08] mb-5"
            style={{ fontFamily: 'Syne, sans-serif' }}
          >
            Distributed<br />File Storage
          </h1>
          <p className="text-blue-200/70 text-[15px] leading-relaxed max-w-[300px] mb-8">
            Files split into chunks, replicated across nodes. Fault-tolerant by design.
          </p>

          <div className="space-y-3">
            {[
              'Chunked uploads with presigned URLs',
              'Multi-node replica distribution',
              'JWT-authenticated secure access',
            ].map((feature) => (
              <div key={feature} className="flex items-center gap-3">
                <div className="w-5 h-5 rounded-full bg-blue-500/25 flex items-center justify-center flex-shrink-0">
                  <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                    <path
                      d="M2 5l2.5 2.5L8 3"
                      stroke="#93C5FD"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </div>
                <span className="text-blue-200/60 text-sm">{feature}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Bottom: Course tag */}
        <div className="relative z-10">
          <span className="text-blue-300/40 text-xs tracking-[0.18em] uppercase font-medium">
            CS559 · Spring 2026
          </span>
        </div>
      </div>

      {/* Right panel */}
      <div className="flex-1 flex items-center justify-center p-8 bg-white">
        <div className="w-full max-w-[340px] fade-up">

          {/* Mobile logo */}
          <div className="flex items-center gap-2.5 mb-10 lg:hidden">
            <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center">
              <NodeIcon size={16} white />
            </div>
            <span className="font-bold text-gray-900" style={{ fontFamily: 'Syne, sans-serif' }}>
              DFS
            </span>
          </div>

          <h2
            className="text-[1.6rem] font-bold text-gray-900 mb-1 leading-tight"
            style={{ fontFamily: 'Syne, sans-serif' }}
          >
            Welcome back
          </h2>
          <p className="text-gray-400 text-sm mb-8">Sign in to access your distributed files.</p>

          <div className="space-y-5">
            <div>
              <Label htmlFor="master-url" className="text-[11px] font-bold text-gray-400 uppercase tracking-widest">
                Server URL
              </Label>
              <Input
                id="master-url"
                type="text"
                value={masterUrl}
                onChange={(e) => setMasterUrlState(e.target.value)}
                className="mt-1.5 font-mono text-sm h-10 border-gray-200 focus-visible:ring-blue-500/30 focus-visible:border-blue-400"
                placeholder="http://localhost"
              />
            </div>

            <div>
              <Label htmlFor="email" className="text-[11px] font-bold text-gray-400 uppercase tracking-widest">
                Email
              </Label>
              <Input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="mt-1.5 h-10 border-gray-200 focus-visible:ring-blue-500/30 focus-visible:border-blue-400"
                placeholder="you@example.com"
              />
            </div>

            <div>
              <Label htmlFor="password" className="text-[11px] font-bold text-gray-400 uppercase tracking-widest">
                Password
              </Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleLogin()}
                className="mt-1.5 h-10 border-gray-200 focus-visible:ring-blue-500/30 focus-visible:border-blue-400"
                placeholder="••••••••"
              />
            </div>

            {error && (
              <div className="rounded-lg bg-red-50 border border-red-100 px-4 py-3 text-sm text-red-600">
                {error}
              </div>
            )}

            <Button
              onClick={handleLogin}
              disabled={loading}
              className="w-full h-11 bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white font-semibold rounded-xl text-sm transition-all mt-1 shadow-[0_2px_12px_rgba(37,99,235,0.3)]"
            >
              {loading ? (
                <span className="flex items-center gap-2">
                  <Spinner />
                  Signing in...
                </span>
              ) : (
                'Sign in'
              )}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

function NodeIcon({ size = 20, white = false }: { size?: number; white?: boolean }) {
  const color = white ? 'white' : 'white'
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" fill="none">
      <circle cx="10" cy="4"  r="2.5" fill={color} />
      <circle cx="3"  cy="15" r="2.5" fill={color} />
      <circle cx="17" cy="15" r="2.5" fill={color} />
      <line x1="10" y1="4" x2="3"  y2="15" stroke={color} strokeWidth="1.4" strokeOpacity="0.65" />
      <line x1="10" y1="4" x2="17" y2="15" stroke={color} strokeWidth="1.4" strokeOpacity="0.65" />
      <line x1="3"  y1="15" x2="17" y2="15" stroke={color} strokeWidth="1.4" strokeOpacity="0.65" />
    </svg>
  )
}

function Spinner() {
  return (
    <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeOpacity="0.25" />
      <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}
