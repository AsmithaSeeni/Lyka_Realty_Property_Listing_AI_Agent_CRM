import React from 'react'

/**
 * Enterprise React Error Boundary to catch render errors gracefully,
 * prevent full page whiteouts/blank screens, and give users actionable recovery steps.
 */
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary caught an error:', error, errorInfo)
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null })
    if (this.props.onReset) {
      this.props.onReset()
    } else {
      window.location.reload()
    }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div
          role="alert"
          style={{
            padding: '2rem',
            margin: '1.5rem',
            borderRadius: '10px',
            background: 'var(--crm-bg-panel, #ffffff)',
            border: '1px solid var(--crm-border-danger, #fca5a5)',
            boxShadow: '0 4px 12px rgba(0,0,0,0.06)',
            color: 'var(--crm-text-primary, #1e293b)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem' }}>
            <span style={{ fontSize: '1.5rem' }}>⚠️</span>
            <h3 style={{ margin: 0, fontSize: '1.15rem', fontWeight: 600 }}>
              {this.props.title || 'An unexpected rendering error occurred'}
            </h3>
          </div>
          <p style={{ margin: '0 0 1rem 0', fontSize: '0.9rem', color: 'var(--crm-text-secondary, #64748b)' }}>
            The interface encountered an error while displaying this component. Your data is safe.
          </p>
          {this.state.error && (
            <pre
              style={{
                padding: '0.75rem 1rem',
                borderRadius: '6px',
                background: '#f8fafc',
                border: '1px solid #e2e8f0',
                fontSize: '0.8rem',
                color: '#b91c1c',
                overflowX: 'auto',
                marginBottom: '1.25rem',
              }}
            >
              {this.state.error.message || String(this.state.error)}
            </pre>
          )}
          <div style={{ display: 'flex', gap: '0.75rem' }}>
            <button
              className="btn btn-primary btn-sm"
              onClick={this.handleReset}
              style={{ padding: '0.45rem 1rem', cursor: 'pointer' }}
            >
              Reload view
            </button>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => window.history.back()}
              style={{ padding: '0.45rem 1rem', cursor: 'pointer' }}
            >
              Go back
            </button>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}

