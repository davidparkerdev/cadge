import { test, expect } from '@playwright/test'

test.describe('Mobile Cadge (MobileActionBar)', () => {
  test.beforeEach(({}, testInfo) => {
    test.skip(testInfo.project.name !== 'mobile', 'Mobile only')
  })

  test('action bar is visible with all 8 buttons', async ({ page }) => {
    await page.goto('/session/new')

    // The MobileActionBar is inside a "md:hidden" container. On mobile viewport
    // its buttons are visible. The ChatInput (in "hidden md:block") also has a
    // "Send message" button but it's hidden by CSS. Use visibility checks.
    const buttonLabels = [
      'Previous session',
      'Start recording',
      'Play response',
      'Next session',
      'Attach image',
      'Type message',
      'Scroll to bottom',
      'Send message',
    ]
    for (const label of buttonLabels) {
      // Use .locator with visible filter to handle the case where both
      // ChatInput and MobileActionBar have buttons with the same aria-label
      const btn = page.locator(`button[aria-label="${label}"]`, {
        has: page.locator(':visible'),
      })
      // At least one should be visible -- check the first visible match
      await expect(
        page.locator(`button[aria-label="${label}"]:visible`).first()
      ).toBeVisible()
    }
  })

  test('desktop textarea is hidden on mobile', async ({ page }) => {
    await page.goto('/session/new')
    // The ChatInput textarea (placeholder "Send a message...") exists in the
    // DOM but is hidden by the "hidden md:block" parent container on mobile.
    await expect(
      page.getByPlaceholder('Send a message...')
    ).toBeHidden()
  })

  test('type modal opens and can be cancelled', async ({ page }) => {
    await page.goto('/session/new')

    // Click the "Type message" button to open TextInputModal
    await page.locator('button[aria-label="Type message"]').click()

    // The modal textarea has placeholder "Type your message..."
    const modalTextarea = page.getByPlaceholder('Type your message...')
    await expect(modalTextarea).toBeVisible()

    // Modal header shows "Type Message"
    await expect(page.getByText('Type Message')).toBeVisible()

    // Type something
    await modalTextarea.fill('Test from modal')
    await expect(modalTextarea).toHaveValue('Test from modal')

    // Close with the Cancel button (aria-label="Cancel")
    await page.locator('button[aria-label="Cancel"]').click()

    // Modal should close -- the modal textarea should disappear
    await expect(modalTextarea).toBeHidden()
  })

  test('type modal send delivers message', async ({ page }) => {
    await page.goto('/session/new')

    // Open the TextInputModal
    await page.locator('button[aria-label="Type message"]').click()

    // The modal textarea has a distinct placeholder
    const modalTextarea = page.getByPlaceholder('Type your message...')
    await expect(modalTextarea).toBeVisible()

    // Type a message
    await modalTextarea.fill('Hello from Cadge')

    // Click the Send button in the modal (aria-label="Send")
    await page.locator('button[aria-label="Send"]').click()

    // Should navigate away from /session/new to a real session
    await expect(page).not.toHaveURL(/\/session\/new/, { timeout: 15000 })

    // User message should be visible in the chat
    await expect(page.getByText('Hello from Cadge')).toBeVisible()
  })

  test('previous/next buttons are disabled on new session', async ({
    page,
  }) => {
    await page.goto('/session/new')

    const prevBtn = page.locator('button[aria-label="Previous session"]')
    const nextBtn = page.locator('button[aria-label="Next session"]')

    await expect(prevBtn).toBeDisabled()
    await expect(nextBtn).toBeDisabled()
  })
})
