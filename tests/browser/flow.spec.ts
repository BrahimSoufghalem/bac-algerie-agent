import { test, expect } from "@playwright/test";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { snapshot, assertNoOverflow, navigate } from "./helpers";
test("owner upload → extract → review → publish → student tool retrieval, stream, source and mobile", async ({
  page,
  browser,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "مرحبًا بعودتك" }),
  ).toBeVisible();
  await snapshot(page, "login-desktop");
  await assertNoOverflow(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await snapshot(page, "login-mobile");
  await assertNoOverflow(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByLabel("البريد الإلكتروني").fill("owner@test.invalid");
  await page.getByLabel("كلمة المرور").fill("Test-password-only-1");
  await page.getByRole("button", { name: "دخول", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "إعدادات الحساب" }),
  ).toBeVisible();
  await navigate(page, "⚙ إعداد النماذج");
  await expect(page.getByLabel("Model", { exact: true })).toHaveValue(
    "offline-test-fixture",
  );
  await snapshot(page, "models-desktop");
  await navigate(page, "▥ إدارة المحتوى");
  const initialCount = (
    await (await page.request.get("/api/library/documents")).json()
  ).items.length;
  const pdf = path.join(process.env.TEST_DATA_DIR!, "scanned_book.pdf");
  execFileSync(process.env.BAC_PYTHON || "python", [
    "tests/fixture_book.py",
    pdf,
  ]);
  await page.locator("input[type=file]").setInputFiles(pdf);
  await page
    .getByLabel("العنوان", { exact: true })
    .fill("مبادئ الحرارة — مصدر اختبار");
  await page
    .getByRole("checkbox", {
      name: "الشعب المستهدفة: علوم تجريبية",
      exact: true,
    })
    .check();
  await page.getByLabel("المادة", { exact: true }).selectOption("physics");
  await page
    .getByLabel("المصدر / المرجع")
    .fill("Synthetic local test, not an official curriculum");
  await page.getByRole("button", { name: "رفع للمراجعة — ليس للنشر" }).click();
  await expect(
    page.getByText("مراجعة النسخة 1", { exact: true }),
  ).toBeVisible();
  const docs = await (await page.request.get("/api/owner/documents")).json();
  const version = docs.items[0].versions[0].id;
  expect(
    (await (await page.request.get("/api/library/documents")).json()).items,
  ).toHaveLength(initialCount);
  await page.getByRole("button", { name: "بدء المعالجة", exact: true }).click();
  await expect
    .poll(
      async () => {
        const v = await (
          await page.request.get("/api/owner/versions/" + version)
        ).json();
        return v.extraction_status;
      },
      { timeout: 30000 },
    )
    .toMatch(/^COMPLETED/);
  await expect(
    page.getByRole("button", { name: /^ص 2 · SUCCESS/ }),
  ).toBeVisible();
  await page.getByRole("button", { name: /^ص 2 · SUCCESS/ }).click();
  await expect(page.getByAltText("صفحة المصدر الأصلية")).toBeVisible();
  await snapshot(page, "owner-review-desktop");
  await page
    .getByLabel("راجعت المصدر وأقرّ بتحذيرات الجودة الظاهرة إن وجدت.")
    .check();
  await page
    .getByLabel("ملاحظات المراجعة")
    .fill(
      "Offline test: all synthetic source elements checked; one intentionally illegible page acknowledged.",
    );
  await page
    .getByRole("button", { name: "اعتماد المراجعة", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "تفعيل للوكيل", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "تفعيل للوكيل", exact: true }).click();
  await expect
    .poll(
      async () =>
        (await (await page.request.get("/api/library/documents")).json()).items
          .length,
    )
    .toBe(initialCount + 1);
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
  });
  const student = await ctx.newPage();
  student.on("pageerror", (e) => errors.push(e.message));
  await student.goto("http://127.0.0.1:8091/");
  await student
    .getByRole("button", { name: "ليس لديك حساب؟ أنشئ حساب طالب" })
    .click();
  await student.getByLabel("الاسم", { exact: true }).fill("طالب اختبار");
  await student.getByLabel("البريد الإلكتروني").fill("student@test.invalid");
  await student.getByLabel("كلمة المرور").fill("Test-student-password-1");
  await student
    .getByRole("button", { name: "إنشاء حساب", exact: true })
    .click();
  await student
    .getByLabel("الشعبة الدراسية", { exact: true })
    .selectOption("experimental_sciences");
  await student.getByRole("button", { name: "تأكيد الشعبة نهائيًا" }).click();
  await student.getByLabel("مادة المحادثة").selectOption("physics");
  await expect(
    student.getByRole("heading", { name: "ما الذي تريد أن تفهمه اليوم؟" }),
  ).toBeVisible();
  await snapshot(student, "chat-empty-desktop");
  expect((await student.request.get("/api/owner/documents")).status()).toBe(
    403,
  );
  await student
    .getByRole("textbox", { name: "رسالتك" })
    .fill("اشرحلي درس الحرارة مع المعادلة.");
  await student.getByRole("button", { name: "إرسال ↑", exact: true }).click();
  await expect(
    student.getByRole("heading", { name: "الحرارة وانتقال الطاقة" }),
  ).toBeVisible({ timeout: 20000 });
  await expect(student.locator(".sources button")).toHaveCount(0);
  await expect(student.locator(".katex-display")).toHaveCount(1);
  await expect(student.locator(".message.assistant figure img")).toHaveCount(0);
  await expect(student.locator(".activity")).toHaveCount(0);
  await snapshot(student, "chat-answer-desktop");
  await assertNoOverflow(student);
  await student.reload();
  await expect(
    student.getByRole("heading", { name: "الحرارة وانتقال الطاقة" }),
  ).toBeVisible();
  await student.setViewportSize({ width: 390, height: 844 });
  await assertNoOverflow(student);
  await snapshot(student, "chat-answer-mobile");
  await student.getByRole("button", { name: "فتح القائمة" }).click();
  await snapshot(student, "menu-mobile");
  await student.getByRole("button", { name: "إغلاق القائمة" }).click();
  await expect(student.locator(".sidebar")).not.toBeVisible();
  expect((await student.request.get("/api/library/documents")).status()).toBe(
    404,
  );
  expect((await student.request.get("/api/agent/books")).status()).toBe(404);
  await expect(
    student.getByRole("button", { name: "المكتبة", exact: true }),
  ).toHaveCount(0);
  await expect(
    student.getByRole("button", { name: "تدريبي الذاتي", exact: true }),
  ).toHaveCount(0);
  await navigate(page, "◷ الاستخدام");
  await expect(
    page.getByRole("heading", { name: "استخدام معلَن، لا تقديرات وهمية" }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("cell", { name: "offline-test-fixture", exact: true })
      .first(),
  ).toBeVisible();
  await snapshot(page, "usage-desktop");
  await navigate(page, "▥ إدارة المحتوى");
  await page
    .locator(".document-row")
    .filter({
      has: page.getByRole("heading", {
        name: "مبادئ الحرارة — مصدر اختبار",
        exact: true,
      }),
    })
    .getByRole("button", { name: "نسخة 1 · PUBLISHED" })
    .click();
  await page.setViewportSize({ width: 390, height: 844 });
  await snapshot(page, "owner-mobile");
  await assertNoOverflow(page);
  expect(errors).toEqual([]);
  await ctx.close();
});
