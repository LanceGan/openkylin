import React from 'react'
import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import App from '../src/App.jsx'

describe('App', () => {
  it('renders without crashing', () => {
    render(<App />)
    expect(screen.getByText('KylinBootLab')).toBeInTheDocument()
  })

  it('renders three tab buttons', () => {
    render(<App />)
    expect(screen.getByText('Boot Timeline')).toBeInTheDocument()
    expect(screen.getByText('Optimization')).toBeInTheDocument()
    expect(screen.getByText('Agent')).toBeInTheDocument()
  })

  it('shows Boot Timeline content by default', () => {
    render(<App />)
    expect(screen.getByText('Boot Phase Breakdown')).toBeInTheDocument()
  })

  it('clicking Optimization tab shows its content', () => {
    render(<App />)
    fireEvent.click(screen.getByText('Optimization'))
    expect(screen.getByText('ABBA Validation Results')).toBeInTheDocument()
  })

  it('clicking Agent tab shows its content', () => {
    render(<App />)
    fireEvent.click(screen.getByText('Agent'))
    expect(screen.getByText('Agent Skill Pipeline')).toBeInTheDocument()
  })
})
