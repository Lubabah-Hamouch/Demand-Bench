import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { Explain } from './Explain'

function renderExplain() {
  render(
    <p>
      <button type="button">Before</button> WAPE
      <Explain term="WAPE" text="What it is." read="Lower is better." />
      <button type="button">After</button>
    </p>,
  )
  return screen.getByRole('button', { name: 'About WAPE' })
}

describe('Explain', () => {
  it('renders a closed, labelled button', () => {
    const button = renderExplain()
    expect(button).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('note')).toBeNull()
  })

  it('is reachable with Tab, opens with Enter, and closes with Escape', async () => {
    const user = userEvent.setup()
    const button = renderExplain()
    await user.tab()
    await user.tab()
    expect(button).toHaveFocus()

    await user.keyboard('{Enter}')
    expect(button).toHaveAttribute('aria-expanded', 'true')
    const note = screen.getByRole('note')
    expect(note).toHaveTextContent('What it is.')
    expect(note).toHaveTextContent('Lower is better.')
    expect(button).toHaveAttribute('aria-controls', note.id)

    await user.keyboard('{Escape}')
    expect(screen.queryByRole('note')).toBeNull()
    expect(button).toHaveAttribute('aria-expanded', 'false')
    expect(button).toHaveFocus()
  })

  it('toggles with Space and with a second click', async () => {
    const user = userEvent.setup()
    const button = renderExplain()
    button.focus()
    await user.keyboard(' ')
    expect(screen.getByRole('note')).toBeInTheDocument()
    await user.click(button)
    expect(screen.queryByRole('note')).toBeNull()
  })

  it('stays open when clicked and closes on a click elsewhere', async () => {
    const user = userEvent.setup()
    const button = renderExplain()
    await user.click(button)
    expect(screen.getByRole('note')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'After' }))
    expect(screen.queryByRole('note')).toBeNull()
  })

  it('opens on mouse hover and closes when the mouse leaves', async () => {
    const user = userEvent.setup()
    const button = renderExplain()
    await user.hover(button)
    expect(screen.getByRole('note')).toHaveTextContent('What it is.')
    await user.unhover(button)
    await waitFor(() => expect(screen.queryByRole('note')).toBeNull())
  })
})
