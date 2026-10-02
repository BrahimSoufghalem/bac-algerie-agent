import { test, expect } from "@playwright/test";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { snapshot, assertNoOverflow, navigate } from "./helpers";
test("whole exam + explicit matched solution ranges → publish → private bundle retrieval without student source access", async ({
  page,
  browser,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.getByLabel("البريد الإلكتروني").fill("owner@test.invalid");
  await page.getByLabel("كلمة المرور").fill("Test-password-only-1");
  await page.getByRole("button", { name: "دخول", exact: true }).click();
  await navigate(page, "▥ إدارة المحتوى");
  const pdf = path.join(process.env.TEST_DATA_DIR!, "exam_heat.pdf");
  execFileSync(process.env.BAC_PYTHON || "python", [
    "tests/fixture_book.py",
    pdf,
  ]);
  await page.locator("input[type=file]").first().setInputFiles(pdf);
  await expect(
    page.getByRole("combobox", { name: "نوع المستند", exact: true }),
  ).toHaveValue("exam");
  await page
    .getByLabel("العنوان", { exact: true })
    .fill("امتحان الحرارة — اختبار غير رسمي");
  await page.getByLabel("المادة", { exact: true }).fill("فيزياء");
  await page.getByLabel("التخصص", { exact: true }).fill("علوم تجريبية");
  await page.getByLabel("السنة", { exact: true }).fill("2025");
  await page.getByLabel("الدورة", { exact: true }).fill("June");
  await page.getByLabel("نوع الامتحان", { exact: true }).fill("BAC");
  await page
    .getByLabel("المصدر / المرجع")
    .fill("Synthetic fixture, not official");
  await page.getByRole("button", { name: "رفع للمراجعة — ليس للنشر" }).click();
  await expect(
    page.getByRole("heading", { name: "الحل المطابق — اختياري" }),
  ).toBeVisible();
  await page
    .getByText("اختيار نطاق الصفحات — PDF مدمج", { exact: true })
    .click();
  await page.getByLabel("آخر صفحة في النطاق").fill("2");
  await page.getByRole("button", { name: "حفظ نطاق الصفحات" }).click();
  await expect(page.locator(".source-files")).toContainText("1–2 / 5");
  await page.getByLabel("الحل موجود داخل PDF الموضوع نفسه").check();
  await page.getByLabel("أول صفحة للحل").fill("3");
  await page.getByLabel("آخر صفحة للحل").fill("4");
  await page
    .getByLabel("مصدر الحل / دليل نسبته")
    .fill(
      "Synthetic supplied solution compared by the test owner; not official",
    );
  await page.getByRole("button", { name: "إرفاق الحل للمراجعة" }).click();
  await expect(
    page.getByText("لن تُعتمد هذه النسخة قبل التحقق من مطابقة الحل ومصدره.", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "اعتماد المراجعة", exact: true }),
  ).toBeDisabled();
  await page
    .getByLabel("قارنت الموضوع بالحل وأؤكد مطابقة المسائل والهوية")
    .check();
  await page
    .getByLabel("راجعت مصدر الحل ووصفه ولا أعتمد تشابه العنوان")
    .check();
  await page
    .getByLabel("دليل المطابقة")
    .fill(
      "Synthetic fixture only: identical supplied identity and exact problem numbering compared by the test owner. Not an official solution.",
    );
  await snapshot(page, "bundle-owner-pending-desktop");
  await page.getByRole("button", { name: "تأكيد مطابقة الحل" }).click();
  await expect(
    page.getByText(
      "المطابقة مؤكدة من المالك؛ ليست شهادة تلقائية برسمية الحل.",
      { exact: true },
    ),
  ).toBeVisible();
  await page.getByRole("button", { name: "بدء المعالجة", exact: true }).click();
  await expect(
    page.getByRole("button", { name: /^الحل · ص 3 · SUCCESS/ }),
  ).toBeVisible({ timeout: 30000 });
  await page.getByRole("button", { name: /^الحل · ص 3 · SUCCESS/ }).click();
  await expect(page.getByAltText("صفحة المصدر الأصلية")).toBeVisible();
  await page
    .getByLabel("راجعت المصدر وأقرّ بتحذيرات الجودة الظاهرة إن وجدت.")
    .check();
  await page
    .getByLabel("ملاحظات المراجعة")
    .fill(
      "Exact statement and supplied solution source/ranges checked in offline test.",
    );
  await page
    .getByRole("button", { name: "اعتماد المراجعة", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "تفعيل للوكيل", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "تفعيل للوكيل", exact: true }).click();
  await expect(page.locator(".version-panel .status").first()).toContainText(
    "PUBLISHED",
  );
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
  });
  const student = await context.newPage();
  student.on("pageerror", (e) => errors.push(e.message));
  await student.goto("http://127.0.0.1:8091/");
  await student
    .getByRole("button", { name: "ليس لديك حساب؟ أنشئ حساب طالب" })
    .click();
  await student.getByLabel("الاسم", { exact: true }).fill("طالب الحزم");
  await student
    .getByLabel("البريد الإلكتروني")
    .fill("bundle-student@test.invalid");
  await student.getByLabel("كلمة المرور").fill("Test-student-password-2");
  await student
    .getByRole("button", { name: "إنشاء حساب", exact: true })
    .click();
  await expect(student.locator(".workspace")).toBeVisible();
  await expect(
    student.getByRole("button", { name: "المكتبة", exact: true }),
  ).toHaveCount(0);
  expect((await student.request.get("/api/library/documents")).status()).toBe(
    404,
  );
  await student
    .getByRole("textbox", { name: "رسالتك" })
    .fill("استدع الامتحان كاملًا مع حله المطابق عن الحرارة.");
  await student.getByRole("button", { name: "إرسال ↑", exact: true }).click();
  await expect(
    student.getByRole("heading", { name: "الحزمة الكاملة من المصدر" }),
  ).toBeVisible({ timeout: 20000 });
  await expect(student.locator(".sources button")).toHaveCount(0);
  await expect(student.locator(".message.assistant img")).toHaveCount(0);
  await snapshot(student, "exam-agent-mobile");
  expect(errors).toEqual([]);
  await context.close();
});

test("exercise collection stays whole and missing solution is explicit", async ({
  page,
  browser,
}) => {
  await page.goto("/");
  await page.getByLabel("البريد الإلكتروني").fill("owner@test.invalid");
  await page.getByLabel("كلمة المرور").fill("Test-password-only-1");
  await page.getByRole("button", { name: "دخول", exact: true }).click();
  await navigate(page, "▥ إدارة المحتوى");
  const pdf = path.join(process.env.TEST_DATA_DIR!, "exercises_heat.pdf");
  execFileSync(process.env.BAC_PYTHON || "python", [
    "tests/fixture_book.py",
    pdf,
  ]);
  await page.locator("input[type=file]").first().setInputFiles(pdf);
  await expect(
    page.getByRole("combobox", { name: "نوع المستند", exact: true }),
  ).toHaveValue("exercise_collection");
  await page
    .getByLabel("العنوان", { exact: true })
    .fill("سلسلة الحرارة — اختبار كامل");
  await page.getByLabel("المادة", { exact: true }).fill("فيزياء");
  await page.getByLabel("التخصص", { exact: true }).fill("علوم تجريبية");
  await page.getByRole("button", { name: "رفع للمراجعة — ليس للنشر" }).click();
  await page.getByRole("button", { name: "بدء المعالجة", exact: true }).click();
  await expect(
    page.getByRole("button", { name: /^ص 5 · NEEDS_REVIEW/ }),
  ).toBeVisible({ timeout: 30000 });
  await page
    .getByLabel("راجعت المصدر وأقرّ بتحذيرات الجودة الظاهرة إن وجدت.")
    .check();
  await page
    .getByLabel("ملاحظات المراجعة")
    .fill(
      "Whole synthetic collection, unreadable final page explicitly acknowledged. No solution supplied.",
    );
  await page
    .getByRole("button", { name: "اعتماد المراجعة", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "تفعيل للوكيل", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "تفعيل للوكيل", exact: true }).click();
  await expect(page.locator(".version-panel .status").first()).toContainText(
    "PUBLISHED",
  );
  const ctx = await browser.newContext({
    viewport: { width: 390, height: 844 },
  });
  const student = await ctx.newPage();
  await student.goto("http://127.0.0.1:8091/");
  await student
    .getByRole("button", { name: "ليس لديك حساب؟ أنشئ حساب طالب" })
    .click();
  await student.getByLabel("الاسم", { exact: true }).fill("طالب السلسلة");
  await student
    .getByLabel("البريد الإلكتروني")
    .fill("collection-student@test.invalid");
  await student.getByLabel("كلمة المرور").fill("Test-student-password-3");
  await student
    .getByRole("button", { name: "إنشاء حساب", exact: true })
    .click();
  await expect(student.locator(".workspace")).toBeVisible();
  await expect(
    student.getByRole("button", { name: "المكتبة", exact: true }),
  ).toHaveCount(0);
  expect((await student.request.get("/api/library/documents")).status()).toBe(
    404,
  );
  await assertNoOverflow(student);
  await student
    .getByRole("textbox", { name: "رسالتك" })
    .fill("استدع سلسلة الحرارة كاملة دون اختراع حل رسمي.");
  await student.getByRole("button", { name: "إرسال ↑", exact: true }).click();
  await expect(
    student.getByRole("heading", { name: "الحزمة الكاملة من المصدر" }),
  ).toBeVisible({ timeout: 20000 });
  await expect(student.locator(".sources button")).toHaveCount(0);
  await expect(student.locator(".message.assistant img")).toHaveCount(0);
  await snapshot(student, "private-collection-chat-mobile");
  await ctx.close();
});
