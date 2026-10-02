import { test, expect, Page } from "@playwright/test";
import { snapshot, assertNoOverflow, navigate } from "./helpers";
async function signIn(
  page: Page,
  email: string,
  password = "Test-learning-password-1",
) {
  await page.goto("/");
  await page.getByLabel("البريد الإلكتروني").fill(email);
  await page.getByLabel("كلمة المرور").fill(password);
  await page.getByRole("button", { name: "دخول", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "إعدادات الحساب", exact: true }),
  ).toBeVisible();
}
async function mobile(page: Page, name: string) {
  await assertNoOverflow(page);
  await snapshot(page, name + "-desktop");
  await page.setViewportSize({ width: 390, height: 844 });
  await assertNoOverflow(page);
  await snapshot(page, name + "-mobile");
}

test("student: preferences → own private image pixels → agent-managed read-only notes → export/delete account", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await signIn(page, "learning@test.invalid");
  await navigate(page, "تفضيلات وخصوصية");
  await page.getByLabel("الشعبة", { exact: true }).fill("علوم تجريبية");
  await page.getByLabel("لغة الشرح").selectOption("fr");
  await page
    .getByRole("button", { name: "حفظ التفضيلات", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("حُفظت التفضيلات");
  await mobile(page, "learning-preferences");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await navigate(page, "＋ محادثة جديدة");
  await page
    .locator('summary[aria-label="إرفاق ملف خاص مؤقتًا · 24 ساعة"]')
    .click();
  // Fixture image from the original synthetic renderer; no remote provider.
  const image = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAMgAAAEYCAIAAACWcy5SAAAC4ElEQVR4nO3SQQ3AIADAQMD/d3LQgKWZWEOy3Cnoo/PZZ8DX1u0A/slYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxFwlgkjEXCWCSMRcJYJIxF4gVtuwRRQQSjmgAAAABJRU5ErkJggg==",
    "base64",
  );
  await page.getByLabel("الملف الخاص", { exact: true }).setInputFiles({
    name: "private.png",
    mimeType: "image/png",
    buffer: image,
  });
  await expect(page.locator(".private-file-row")).toContainText("private.png");
  await page
    .getByLabel("رسالتك")
    .fill("اقرأ ملف خاص ثم اقترح هدف مراجعة دون اعتماده");
  await page.getByRole("button", { name: "إرسال ↑", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "قرأت الملف الخاص" }),
  ).toBeVisible({ timeout: 30000 });
  await expect(page.locator(".message.assistant img")).toHaveCount(0);
  await mobile(page, "learning-private-answer");
  await navigate(page, "ملاحظات مسار التعليمية");
  await expect(
    page.getByRole("heading", { name: "ملاحظات مسار التعليمية" }),
  ).toBeVisible();
  await expect(
    page.getByText("تبسيط تحويل الوحدات وفق التعلّم."),
  ).toBeVisible();
  await expect(page.getByRole("textbox", { name: "نص الملاحظة" })).toHaveCount(
    0,
  );
  await expect(page.getByRole("button", { name: "حذف الملاحظة" })).toHaveCount(
    0,
  );
  await mobile(page, "learning-notes-readonly");
  await navigate(page, "تفضيلات وخصوصية");
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "تصدير بياناتي JSON" }).click();
  expect((await download).suggestedFilename()).toContain("export");
  expect(errors).toEqual([]);
});
for (const who of ["teacher"])
  test(`${who}: same agent engine → role-specific material tool → saved private draft/rubric/solution → reload`, async ({
    page,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await signIn(page, who + "@test.invalid");
    await navigate(page, "مساحة إعداد الأستاذ");
    await page
      .getByRole("combobox", { name: "المهمة", exact: true })
      .selectOption("exam");
    await page
      .getByLabel("الموضوع أو إجابة الطالب التي لديك")
      .fill("حساب بسيط");
    await page
      .getByRole("button", { name: "بدء إعداد مسودة", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "حُفظت المسودة الخاصة" }),
    ).toBeVisible({ timeout: 30000 });
    await navigate(page, "مساحة إعداد الأستاذ");
    await page
      .getByRole("button", { name: "عرض المسودة", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "سؤال مولّد تجريبي" }),
    ).toBeVisible();
    await expect(page.locator("table tbody")).toContainText("الناتج");
    await page
      .getByText("الحل المنفصل — مولّد، راجعه", { exact: true })
      .click();
    await expect(page.locator(".material-solution")).toContainText("حل مولّد");
    await mobile(page, "learning-material-" + who);
    const materials = await (await page.request.get("/api/materials")).json();
    expect(materials.items.at(-1).payload.official).toBe(false);
    await page.reload();
    await navigate(page, "مساحة إعداد الأستاذ");
    await expect(
      page.getByRole("button", { name: "عرض المسودة", exact: true }),
    ).toBeVisible();
    expect(errors).toEqual([]);
  });
test("owner: accounts limits and immutable model prices; no implicit paid connection test", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await signIn(page, "owner@test.invalid", "Test-password-only-1");
  await navigate(page, "الحسابات والحدود");
  await page.getByLabel("اسم الحساب", { exact: true }).fill("أستاذ جديد");
  await page.getByLabel("بريد الحساب").fill("created-teacher@test.invalid");
  await page
    .getByLabel("كلمة المرور الأولية")
    .fill("Test-new-teacher-password");
  await page.getByRole("button", { name: "إنشاء الحساب", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "أستاذ جديد", exact: true }),
  ).toBeVisible();
  const form = page.locator("form").filter({
    has: page.getByRole("heading", { name: "أستاذ جديد", exact: true }),
  });
  await form.getByLabel("تشغيلات يومية (0 يمنع التشغيل)").fill("0");
  await form.getByRole("button", { name: "حفظ حدود أستاذ جديد" }).click();
  await expect(page.getByRole("status")).toContainText("حُفظت حدود الحساب");
  await mobile(page, "learning-accounts");
  await navigate(page, "⚙ إعداد النماذج");
  await page.getByLabel("سعر الإدخال", { exact: true }).fill("1");
  await expect(page.getByLabel("سعر الإدخال", { exact: true })).toHaveValue(
    "1",
  );
  await page.getByLabel("سعر الإخراج", { exact: true }).fill("2");
  await page
    .getByLabel("سعر الإدخال المخزّن Cache", { exact: true })
    .fill("0.25");
  await page.getByRole("button", { name: "حفظ الإعداد", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("لم يُرسل طلب");
  await expect(
    page.getByRole("button", { name: "اختبار الاتصال المحفوظ" }),
  ).toBeVisible();
  await mobile(page, "learning-prices");
  expect(errors).toEqual([]);
});
