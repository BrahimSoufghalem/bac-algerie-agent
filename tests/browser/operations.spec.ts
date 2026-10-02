import { test, expect, Page } from "@playwright/test";
import { snapshot, assertNoOverflow, navigate } from "./helpers";
async function signIn(page: Page, email: string, password: string) {
  await page.goto("/");
  await page.getByLabel("البريد الإلكتروني").fill(email);
  await page.getByLabel("كلمة المرور", { exact: true }).fill(password);
  await page.getByRole("button", { name: "دخول", exact: true }).click();
  await expect(page.locator(".workspace")).toBeVisible();
}
test("security: password change invalidates second browser session, mobile-safe forms", async ({
  page,
  browser,
}) => {
  await signIn(page, "security@test.invalid", "Test-security-password-1");
  const other = await browser.newContext();
  const p = await other.newPage();
  await signIn(p, "security@test.invalid", "Test-security-password-1");
  await navigate(page, "أمان الحساب");
  await assertNoOverflow(page);
  await snapshot(page, "security-desktop");
  await page.setViewportSize({ width: 390, height: 844 });
  await assertNoOverflow(page);
  await snapshot(page, "security-mobile");
  await page
    .getByLabel("كلمة المرور الحالية", { exact: true })
    .fill("Test-security-password-1");
  await page
    .getByLabel("كلمة المرور الجديدة", { exact: true })
    .fill("Changed-security-password-123");
  await page
    .getByRole("button", { name: "تغيير وإلغاء الجلسات", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "دخول", exact: true }),
  ).toBeVisible();
  const denied = await other.request.get("/api/auth/me");
  expect(denied.status()).toBe(401);
  await other.close();
  await signIn(page, "security@test.invalid", "Changed-security-password-123");
});
test("recovery: unconfigured mail is explicit; link kept out of URL after loading", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: "نسيت كلمة المرور أو تأكيد البريد؟" })
    .click();
  await expect(page.getByRole("status")).toContainText("خدمة البريد غير مهيأة");
  await expect(
    page.getByRole("button", { name: "إرسال الرابط", exact: true }),
  ).toBeDisabled();
  await page.setViewportSize({ width: 390, height: 844 });
  await assertNoOverflow(page);
  await snapshot(page, "recovery-mobile");
  await page.goto(
    "/#auth=reset:invalid-token-which-is-at-least-thirty-two-characters",
  );
  await expect(page.getByLabel("كلمة المرور الجديدة")).toBeVisible();
  expect(new URL(page.url()).hash).toBe("");
  await page
    .getByLabel("كلمة المرور الجديدة")
    .fill("New-recovery-password-123");
  await page.getByRole("button", { name: "تأكيد التحديث" }).click();
  await expect(page.getByRole("status")).toContainText("Invalid or expired");
});
test("owner: no new external source credentials or credential navigation", async ({
  page,
}) => {
  await signIn(page, "owner@test.invalid", "Test-password-only-1");
  await page
    .getByRole("button", { name: "إعدادات الحساب", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "وصول الوكلاء", exact: true }),
  ).toHaveCount(0);
  expect(
    (
      await page.request.get("/api/agent/books", {
        headers: { Authorization: "Bearer mbac_legacy" },
      })
    ).status(),
  ).toBe(403);
});
