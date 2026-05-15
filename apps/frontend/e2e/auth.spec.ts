import { test, expect } from '@playwright/test';

test.describe('Authentication', () => {
  test('login page renders correctly', async ({ page }) => {
    await page.goto('/login');
    await expect(page.getByRole('heading', { name: /sign in|log in/i })).toBeVisible();
    await expect(page.getByLabel(/email/i)).toBeVisible();
    await expect(page.getByLabel(/password/i)).toBeVisible();
  });

  test('signup page renders correctly', async ({ page }) => {
    await page.goto('/signup');
    await expect(page.getByLabel(/email/i)).toBeVisible();
    await expect(page.getByLabel(/password/i)).toBeVisible();
    await expect(page.getByLabel(/first name/i)).toBeVisible();
  });

  test('unauthenticated user is redirected to login', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveURL(/\/login/);
  });

  test('login with invalid credentials shows error', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel(/email/i).fill('invalid@test.com');
    await page.getByLabel(/password/i).fill('wrongpassword');
    await page.getByRole('button', { name: /sign in|log in/i }).click();
    await expect(page.getByText(/invalid|unauthorized|error/i)).toBeVisible({ timeout: 5000 });
  });
});

test.describe('Navigation', () => {
  test('login page has link to signup', async ({ page }) => {
    await page.goto('/login');
    await expect(page.getByRole('link', { name: /sign up|register|create/i })).toBeVisible();
  });

  test('signup page has link to login', async ({ page }) => {
    await page.goto('/signup');
    await expect(page.getByRole('link', { name: /sign in|log in/i })).toBeVisible();
  });
});
