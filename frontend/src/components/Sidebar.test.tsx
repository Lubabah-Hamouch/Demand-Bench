import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { requestsTo } from '../test/server'
import { Sidebar } from './Sidebar'

/** The series rows in the sidebar, in display order. */
const seriesRows = () =>
  within(screen.getByRole('complementary', { name: 'Choose a series' }))
    .queryAllByRole('button')
    .filter((b) => /units \/ 4 wk/.test(b.textContent ?? ''))

function renderSidebar(onSelect = vi.fn()) {
  render(
    <Sidebar
      selected={{ itemId: 'FOODS_3_090', storeId: 'CA_1' }}
      onSelect={onSelect}
      nSeries={30490}
      drawer={false}
      open={false}
      onClose={() => {}}
    />,
  )
  return onSelect
}

describe('Sidebar', () => {
  it('lists series by their real hierarchy, with the raw id as secondary text', async () => {
    renderSidebar()
    await waitFor(() => expect(seriesRows()).toHaveLength(4))
    const first = seriesRows()[0]
    expect(first).toHaveTextContent('Foods / Dept. 3')
    expect(first).toHaveTextContent('Item 090')
    expect(first).toHaveTextContent('California, Store 1')
    expect(first).toHaveTextContent('FOODS_3_090 · CA_1')
    expect(first).toHaveAttribute('aria-current', 'true')
    expect(screen.getByText(/4 of 4 matching series shown \(30,490 in total\)/)).toBeInTheDocument()
  })

  it('filters by search text, turning words into API filters', async () => {
    const user = userEvent.setup()
    renderSidebar()
    await waitFor(() => expect(seriesRows()).toHaveLength(4))

    await user.type(screen.getByLabelText('Search item, department or store'), 'Hobbies')
    await waitFor(() => expect(seriesRows()).toHaveLength(1))
    expect(seriesRows()[0]).toHaveTextContent('Item 008')
    expect(requestsTo('GET', /^\/series$/).at(-1)?.params).toMatchObject({ q: 'hobbies' })

    await user.clear(screen.getByLabelText('Search item, department or store'))
    await user.type(screen.getByLabelText('Search item, department or store'), 'foods texas')
    await waitFor(() => expect(seriesRows()[0]).toHaveTextContent('Texas, Store 3'))
    expect(seriesRows()).toHaveLength(1)
    expect(requestsTo('GET', /^\/series$/).at(-1)?.params).toMatchObject({ q: 'foods', state_id: 'TX' })
  })

  it('debounces the search so typing does not send a request per keystroke', async () => {
    const user = userEvent.setup()
    renderSidebar()
    await waitFor(() => expect(seriesRows()).toHaveLength(4))
    const before = requestsTo('GET', /^\/series$/).length

    await user.type(screen.getByLabelText('Search item, department or store'), 'household')
    await waitFor(() => expect(seriesRows()).toHaveLength(1))
    // Nine keystrokes, one request for the final text.
    const searches = requestsTo('GET', /^\/series$/).slice(before)
    expect(searches.map((r) => r.params.q)).toEqual(['household'])
  })

  it('filters by volume tier', async () => {
    const user = userEvent.setup()
    renderSidebar()
    await waitFor(() => expect(seriesRows()).toHaveLength(4))
    await user.click(screen.getByRole('button', { name: 'Med' }))
    await waitFor(() => expect(seriesRows()).toHaveLength(1))
    expect(requestsTo('GET', /^\/series$/).at(-1)?.params).toMatchObject({ volume_tier: 'medium' })
    expect(screen.getByRole('button', { name: 'Med' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('selects a series when its row is clicked', async () => {
    const user = userEvent.setup()
    const onSelect = renderSidebar()
    await waitFor(() => expect(seriesRows()).toHaveLength(4))
    await user.click(seriesRows().find((r) => r.textContent?.includes('Texas, Store 3') && r.textContent.includes('Item 586'))!)
    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onSelect.mock.calls[0][0]).toMatchObject({ item_id: 'FOODS_3_586', store_id: 'TX_3' })
  })

  it('says when nothing matches', async () => {
    const user = userEvent.setup()
    renderSidebar()
    await user.type(screen.getByLabelText('Search item, department or store'), 'zzz')
    expect(await screen.findByText('Nothing matches that search.')).toBeInTheDocument()
  })
})
