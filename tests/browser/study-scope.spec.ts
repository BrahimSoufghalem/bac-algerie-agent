import { test, expect } from "@playwright/test";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { navigate, snapshot, assertNoOverflow } from "./helpers";

test("mandatory immutable first track and subject switch opens another conversation", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.getByLabel("البريد الإلكتروني").fill("study-new@test.invalid");
  await page.getByLabel("كلمة المرور").fill("Test-learning-password-1");
  await page.getByRole("button", { name: "دخول", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "اختر شعبتك الدراسية" }),
  ).toBeVisible();
  await expect(page.getByLabel("رسالتك")).toHaveCount(0);
  await expect(
    page.getByLabel("الشعبة الدراسية").locator("option"),
  ).toHaveCount(7);
  await snapshot(page, "study-onboarding-desktop");
  await page.setViewportSize({ width: 390, height: 844 });
  await assertNoOverflow(page);
  await snapshot(page, "study-onboarding-mobile");
  await page
    .getByLabel("الشعبة الدراسية")
    .selectOption("experimental_sciences");
  await page.getByRole("button", { name: "تأكيد الشعبة نهائيًا" }).click();
  const csrf = (await (await page.request.get("/api/auth/me")).json()).csrf;
  expect(
    (
      await page.request.put("/api/auth/study-track", {
        data: { value: "mathematics" },
        headers: { "X-CSRF-Token": csrf },
      })
    ).status(),
  ).toBe(409);
  await page.getByLabel("مادة المحادثة").selectOption("physics");
  await page.getByLabel("رسالتك").fill("اشرح الحرارة");
  await page.getByRole("button", { name: "إرسال ↑", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "الحرارة وانتقال الطاقة" }),
  ).toBeVisible({ timeout: 30000 });
  const old = new URL(page.url()).hash.slice(6);
  await page.getByLabel("مادة المحادثة").selectOption("mathematics");
  await expect(page.getByRole("status")).toContainText("فُتحت محادثة جديدة");
  const next = new URL(page.url()).hash.slice(6);
  expect(next).not.toBe(old);
  const previous = await (
    await page.request.get("/api/conversations/" + old)
  ).json();
  expect(previous.study_subject).toBe("physics");
  expect(previous.messages.length).toBe(2);
  expect(
    (await (await page.request.get("/api/conversations/" + next)).json())
      .messages,
  ).toHaveLength(0);
  await assertNoOverflow(page);
  await snapshot(page, "study-subject-mobile");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await snapshot(page, "study-subject-desktop");
  expect(errors).toEqual([]);
});

test("owner fixed choices and combined/separate uploads are linked in one request", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByLabel("البريد الإلكتروني").fill("owner@test.invalid");
  await page.getByLabel("كلمة المرور").fill("Test-password-only-1");
  await page.getByRole("button", { name: "دخول", exact: true }).click();
  await navigate(page, "▥ إدارة المحتوى");
  await expect(
    page.getByLabel("نوع المحتوى", { exact: true }).locator("option"),
  ).toHaveCount(4);
  const file = path.join(process.env.TEST_DATA_DIR!, "study-pair.pdf");
  execFileSync(process.env.BAC_PYTHON || "python", [
    "tests/fixture_book.py",
    file,
  ]);
  await page.getByLabel("اختر ملف PDF", { exact: true }).setInputFiles(file);
  await page
    .getByRole("checkbox", {
      name: "الشعب المستهدفة: علوم تجريبية",
      exact: true,
    })
    .check();
  await page.getByLabel("المادة", { exact: true }).selectOption("physics");
  await page
    .getByLabel("نوع المحتوى", { exact: true })
    .selectOption("bac_exams");
  await page.getByLabel("تنسيق الملفات").selectOption("combined");
  await page.getByLabel("آخر صفحة للموضوع", { exact: true }).fill("2");
  await page.getByLabel("أول صفحة للحل", { exact: true }).fill("3");
  await page.getByLabel("آخر صفحة للحل", { exact: true }).fill("5");
  await page
    .getByLabel("أؤكد أن الحل المرفق يخص هذا الموضوع ونفس الشعبة والمادة.")
    .check();
  await snapshot(page, "study-owner-combined-desktop");
  await page.setViewportSize({ width: 390, height: 844 });
  await assertNoOverflow(page);
  await snapshot(page, "study-owner-combined-mobile");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("button", { name: "رفع للمراجعة — ليس للنشر" }).click();
  await expect(page.locator(".source-files")).toContainText("3–5 / 5");
  const me = await (await page.request.get("/api/auth/me")).json();
  const csrf = me.csrf;
  const meta = JSON.stringify({
    kind: "exam",
    content_type: "school_tests",
    subject: "physics",
    track: "experimental_sciences",
    title: "two separate files",
  });
  const r = await page.request.post("/api/owner/documents/upload", {
    headers: { "X-CSRF-Token": csrf },
    multipart: {
      metadata: meta,
      package: JSON.stringify({ layout: "separate", matching_confirmed: true }),
      file: {
        name: "statement.pdf",
        mimeType: "application/pdf",
        buffer: execFileSync(process.env.BAC_PYTHON || "python", [
          "-c",
          `import sys,pymupdf;d=pymupdf.open();d.new_page().insert_text((30,30),'Statement');sys.stdout.buffer.write(d.tobytes())`,
        ]),
      },
      solution_file: {
        name: "answer.pdf",
        mimeType: "application/pdf",
        buffer: execFileSync(process.env.BAC_PYTHON || "python", [
          "-c",
          `import sys,pymupdf;d=pymupdf.open();d.new_page().insert_text((30,30),'Answer');sys.stdout.buffer.write(d.tobytes())`,
        ]),
      },
    },
  });
  expect(r.status()).toBe(200);
  const result = await r.json();
  expect(result.solution_linked).toBe(true);
  const version = await (
    await page.request.get("/api/owner/versions/" + result.version_id)
  ).json();
  expect(version.files).toHaveLength(2);
  expect(version.status).toBe("UPLOADED");
});
