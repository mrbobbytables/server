(() => {
  const sessionKey = 'kc-has-session'
  const healthURL = 'http://127.0.0.1:8585/health'
  const gateID = 'kubestellar-kiosk-gate'

  const INITIAL_BACKOFF_MS = 500
  const BACKOFF_FACTOR = 2
  const MAX_RETRIES = 4
  const STAGGER_INTERVAL_MS = 75

  let lastDispatchTime = -STAGGER_INTERVAL_MS

  const sleep = (ms, signal) => new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('Aborted', 'AbortError'))
      return
    }
    const timer = setTimeout(resolve, ms)
    signal?.addEventListener('abort', () => {
      clearTimeout(timer)
      reject(new DOMException('Aborted', 'AbortError'))
    }, { once: true })
  })

  const isApiRequest = (input) => {
    try {
      let urlStr
      if (typeof input === 'string') {
        urlStr = input
      } else if (input instanceof URL) {
        urlStr = input.href
      } else if (input && typeof input === 'object' && 'url' in input) {
        urlStr = input.url
      } else {
        urlStr = String(input)
      }

      const origin = typeof window !== 'undefined' && window.location ? window.location.origin : 'http://localhost'
      const parsed = new URL(urlStr, origin)
      return parsed.origin === origin && (parsed.pathname === '/api' || parsed.pathname.startsWith('/api/'))
    } catch {
      return false
    }
  }

  const staggerRequest = async (signal) => {
    const now = Date.now()
    const scheduledTime = Math.max(now, lastDispatchTime + STAGGER_INTERVAL_MS)
    lastDispatchTime = scheduledTime
    const waitMs = scheduledTime - now
    if (waitMs > 0) {
      await sleep(waitMs, signal)
    }
  }

  const parseRetryAfter = (response) => {
    try {
      const header = response.headers?.get?.('Retry-After')
      if (!header) return null
      const seconds = Number(header)
      if (!Number.isNaN(seconds) && seconds >= 0) {
        return seconds * 1000
      }
      const dateMs = Date.parse(header)
      if (!Number.isNaN(dateMs)) {
        const diff = dateMs - Date.now()
        return diff > 0 ? diff : 0
      }
    } catch {
      // fallback
    }
    return null
  }

  const executeFetch = (originalFetch, input, init) => {
    if (typeof Request !== 'undefined' && input instanceof Request) {
      try {
        return originalFetch(input.clone(), init)
      } catch {
        return originalFetch(input, init)
      }
    }
    return originalFetch(input, init)
  }

  if (typeof window !== 'undefined' && typeof window.fetch === 'function') {
    const originalFetch = window.fetch.bind(window)

    window.fetch = async function (input, init) {
      if (!isApiRequest(input)) {
        return originalFetch(input, init)
      }

      const signal = init?.signal || (typeof Request !== 'undefined' && input instanceof Request ? input.signal : undefined)
      if (signal?.aborted) {
        throw new DOMException('The user aborted a request.', 'AbortError')
      }

      await staggerRequest(signal)

      let attempt = 0
      while (true) {
        const response = await executeFetch(originalFetch, input, init)
        if (response.status !== 429 || attempt >= MAX_RETRIES) {
          return response
        }

        attempt++
        const retryAfterMs = parseRetryAfter(response)
        const backoffMs = retryAfterMs !== null
          ? retryAfterMs
          : INITIAL_BACKOFF_MS * Math.pow(BACKOFF_FACTOR, attempt - 1)

        await sleep(backoffMs, signal)
      }
    }
  }

  const hasSession = () => {
    try {
      return window.localStorage.getItem(sessionKey) === 'true'
    } catch {
      return false
    }
  }

  const removeGate = () => document.getElementById(gateID)?.remove()

  const showGate = () => {
    if (document.getElementById(gateID)) return

    document.body.insertAdjacentHTML('beforeend', `
      <section id="${gateID}" class="kiosk-gate" role="dialog" aria-modal="true">
        <div class="kiosk-gate__dialog">
          <h1>Connect the kc-agent</h1>
          <p>Monitor your real clusters from this console</p>
          <p>Run agent on machine access kubeconfig</p>
          <code>brew tap kubestellar/tap && brew install kc-agent</code>
          <code>KAGENTI_CONTROLLER_URL="none" kc-agent -allowed-origins ${window.location.origin}</code>
        </div>
      </section>
    `)
  }

  const updateGate = async () => {
    if (!hasSession()) {
      removeGate()
      return
    }

    try {
      const response = await fetch(healthURL, { credentials: 'omit' })
      if (!response.ok) throw new Error(`kc-agent health: ${response.status}`)
      removeGate()
    } catch {
      showGate()
    }
  }

  if (typeof document !== 'undefined') {
    document.addEventListener('keydown', (event) => {
      const gate = document.getElementById(gateID)
      if (gate && !gate.contains(event.target)) event.preventDefault()
    }, true)
  }

  if (typeof window !== 'undefined') {
    window.setInterval(() => void updateGate(), 2_000)
    void updateGate()
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
      isApiRequest,
      parseRetryAfter,
      staggerRequest,
      INITIAL_BACKOFF_MS,
      BACKOFF_FACTOR,
      MAX_RETRIES,
      STAGGER_INTERVAL_MS,
    }
  }
})()
