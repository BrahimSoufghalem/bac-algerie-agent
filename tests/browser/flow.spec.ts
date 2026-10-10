import { test, expect } from "@playwright/test";
import { chooseSubject, assertNoOverflow } from "./helpers";
test("student privately retrieves a published Markdown lesson, streams and renders on mobile", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByLabel("البريد الإلكتروني").fill("learning@test.invalid");
  await page.getByLabel("كلمة المرور").fill("Test-learning-password-1");
  await page.getByRole("button", { name: "دخول", exact: true }).click();
  if (
    await page.getByRole("heading", { name: "اختر شعبتك الدراسية" }).count()
  ) {
    await page
      .getByLabel("الشعبة الدراسية")
      .selectOption("experimental_sciences");
    await page.getByRole("button", { name: "تأكيد الشعبة نهائيًا" }).click();
  }
  await chooseSubject(page, "physics");
  await page.getByLabel("رسالتك").fill("اشرح الحرارة");
  await page.getByRole("button", { name: "إرسال ↑", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "الحرارة وانتقال الطاقة" }),
  ).toBeVisible({ timeout: 30000 });
  expect((await page.request.get("/api/library/documents")).status()).toBe(404);
  await page.setViewportSize({ width: 390, height: 844 });
  await assertNoOverflow(page);
});
