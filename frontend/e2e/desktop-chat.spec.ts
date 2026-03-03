import { test, expect } from '@playwright/test'

const API_URL = 'http://localhost:33401'

test.describe('Desktop Chat', () => {
  test.beforeEach(({}, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop', 'Desktop only')
  })

  test('loads the app and redirects to /session/new', async ({ page }) => {
    await page.goto('/')
    // Should redirect to /session/new
    await expect(page).toHaveURL(/\/session\/new/)
    // Desktop: the ChatInput textarea (placeholder "Send a message...") should be visible
    await expect(
      page.getByPlaceholder('Send a message...')
    ).toBeVisible()
  })

  test('can type and send a message', async ({ page }) => {
    await page.goto('/session/new')
    // Use the specific ChatInput textarea by placeholder
    const textarea = page.getByPlaceholder('Send a message...')
    await expect(textarea).toBeVisible()
    await textarea.fill('Hello from Playwright')

    // The ChatInput send button is inside the "hidden md:block" container.
    // Both ChatInput and MobileActionBar have aria-label="Send message", so
    // scope to the visible one on desktop.
    const desktopSendBtn = page
      .locator('.hidden.md\\:block button[aria-label="Send message"]')
    await desktopSendBtn.click()

    // Should navigate away from /session/new to /session/<uuid>
    await expect(page).not.toHaveURL(/\/session\/new/, { timeout: 15000 })
    // The user message should appear in the chat
    await expect(page.getByText('Hello from Playwright')).toBeVisible()
  })

  test('sidebar shows session list with created session', async ({ page }) => {
    // Create a session via API
    const res = await page.request.post(`${API_URL}/api/sessions`, {
      data: { title: 'E2E Desktop Test Session' },
    })
    expect(res.ok()).toBeTruthy()
    const session = await res.json()

    await page.goto(`/session/${session.id}`)
    // Sidebar should be visible on desktop and show the session title
    await expect(
      page.getByText('E2E Desktop Test Session')
    ).toBeVisible()

    // Cleanup
    await page.request.delete(`${API_URL}/api/sessions/${session.id}`)
  })
})
