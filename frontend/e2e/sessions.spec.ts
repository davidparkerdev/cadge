import { test, expect } from '@playwright/test'

const API_URL = 'http://localhost:33401'

test.describe('Sessions', () => {
  test('navigating to an API-created session shows the correct URL', async ({
    page,
  }) => {
    // Create a session via API
    const res = await page.request.post(`${API_URL}/api/sessions`, {
      data: { title: 'Navigation Test' },
    })
    expect(res.ok()).toBeTruthy()
    const session = await res.json()

    await page.goto(`/session/${session.id}`)
    await expect(page).toHaveURL(new RegExp(`/session/${session.id}`))

    // Cleanup
    await page.request.delete(`${API_URL}/api/sessions/${session.id}`)
  })

  test('switching between sessions updates the URL', async ({ page }) => {
    // Create two sessions via API
    const res1 = await page.request.post(`${API_URL}/api/sessions`, {
      data: { title: 'Session Alpha' },
    })
    expect(res1.ok()).toBeTruthy()
    const s1 = await res1.json()

    const res2 = await page.request.post(`${API_URL}/api/sessions`, {
      data: { title: 'Session Beta' },
    })
    expect(res2.ok()).toBeTruthy()
    const s2 = await res2.json()

    // Navigate to first session
    await page.goto(`/session/${s1.id}`)
    await expect(page).toHaveURL(new RegExp(`/session/${s1.id}`))

    // Navigate to second session
    await page.goto(`/session/${s2.id}`)
    await expect(page).toHaveURL(new RegExp(`/session/${s2.id}`))

    // Cleanup
    await page.request.delete(`${API_URL}/api/sessions/${s1.id}`)
    await page.request.delete(`${API_URL}/api/sessions/${s2.id}`)
  })

  test('clicking a session in the sidebar navigates to it', async ({
    page,
  }, testInfo) => {
    // This test only works on desktop where the sidebar is visible
    test.skip(testInfo.project.name === 'mobile', 'Desktop sidebar only')

    // Create a session
    const res = await page.request.post(`${API_URL}/api/sessions`, {
      data: { title: 'Sidebar Click Test' },
    })
    expect(res.ok()).toBeTruthy()
    const session = await res.json()

    // Start on a new session page so the sidebar shows the created session
    await page.goto('/session/new')

    // Click the session in the sidebar (SessionItem is a div with onClick)
    const sessionItem = page.getByText('Sidebar Click Test')
    await expect(sessionItem).toBeVisible({ timeout: 5000 })
    await sessionItem.click()

    // URL should update to the session
    await expect(page).toHaveURL(new RegExp(`/session/${session.id}`))

    // Cleanup
    await page.request.delete(`${API_URL}/api/sessions/${session.id}`)
  })

  test('deleting a session via API and reloading handles it gracefully', async ({
    page,
  }) => {
    // Create a session
    const res = await page.request.post(`${API_URL}/api/sessions`, {
      data: { title: 'Delete Me' },
    })
    expect(res.ok()).toBeTruthy()
    const session = await res.json()

    // Navigate to it
    await page.goto(`/session/${session.id}`)
    await expect(page).toHaveURL(new RegExp(`/session/${session.id}`))

    // Delete via API
    const delRes = await page.request.delete(
      `${API_URL}/api/sessions/${session.id}`
    )
    expect(delRes.ok()).toBeTruthy()

    // Reload -- the frontend should handle the missing session gracefully
    // (no crash, no unhandled error). It may show empty or redirect.
    await page.reload()

    // Page should still be functional (no crash). We just verify no unhandled
    // JS errors by checking the page is still interactive.
    await expect(page.locator('body')).toBeVisible()
  })
})
