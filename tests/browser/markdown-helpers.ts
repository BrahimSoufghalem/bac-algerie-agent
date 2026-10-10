import { expect, Page } from "@playwright/test";
import { navigate } from "./helpers";
export const SOURCE = `## [صفحة الكتاب 1 / صفحة PDF 1]
# شحن المكثفة
يتطور التوتر أثناء الشحن وفق العلاقة التالية؛ ثابت الزمن يساوي RC.

$$
u_C=E(1-e^{-t/RC})
$$

section_id: "1"
title: "شحن المكثفة"
summary: "شحن المكثفة وثابت الزمن والتوتر والتيار."
covers:
  - "ثابت الزمن RC"
  - "تطور التوتر"
`;
export async function signIn(page: Page) {
  await page.goto("/");
  await page.getByLabel("البريد الإلكتروني").fill("owner@test.invalid");
  await page.getByLabel("كلمة المرور").fill("Test-password-only-1");
  await page.getByRole("button", { name: "دخول", exact: true }).click();
  await navigate(page, "▥ إدارة المحتوى");
}
export async function publish(page: Page) {
  await page.getByLabel("راجعت النص والتحذيرات وأوافق على اعتماده.").check();
  await page
    .getByRole("button", { name: "اعتماد المراجعة", exact: true })
    .click();
  await page.getByRole("button", { name: "نشر المحتوى", exact: true }).click();
  await expect(
    page.getByText("هذه النسخة منشورة", { exact: true }),
  ).toBeVisible();
}
export async function add(
  page: Page,
  title: string,
  type = "textbook",
  tracks = ["علوم تجريبية"],
) {
  await page
    .getByLabel("اختر ملفات Markdown", { exact: false })
    .setInputFiles({
      name: title + ".md",
      mimeType: "text/markdown",
      buffer: Buffer.from(SOURCE),
    });
  await page.getByLabel("نوع المحتوى", { exact: true }).selectOption(type);
  for (const label of tracks)
    await page
      .getByRole("checkbox", { name: "الشعب المستهدفة: " + label, exact: true })
      .check();
  await page.getByLabel("المادة", { exact: true }).selectOption("physics");
  await page.getByLabel("العنوان", { exact: false }).fill(title);
  await page
    .getByRole("button", { name: "استيراد الملفات", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "معاينة قبل النشر", exact: true }),
  ).toBeVisible();
}
