import { test, expect } from "@playwright/test";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { snapshot, assertNoOverflow, navigate } from "./helpers";

test("owner explicitly re-extracts one successful page into a draft, preserving published content until review", async ({
  page,
}) => {
  const errors: string[] = [];
  const requests: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().endsWith("/reextract"))
      requests.push(r.url());
  });
  await page.goto("/");
  await page.getByLabel("البريد الإلكتروني").fill("owner@test.invalid");
  await page.getByLabel("كلمة المرور").fill("Test-password-only-1");
  await page.getByRole("button", { name: "دخول", exact: true }).click();
  await navigate(page, "▥ إدارة المحتوى");
  const pdf = path.join(process.env.TEST_DATA_DIR!, "manual-two-pages.pdf");
  execFileSync(process.env.BAC_PYTHON || "python", [
    "-c",
    `import pymupdf,sys
from pathlib import Path
Path(sys.argv[1]).parent.mkdir(parents=True, exist_ok=True)
with pymupdf.open() as d:
 for i in range(2): d.new_page().insert_text((40,40),f'Manual page fixture {i+1}')
 d.save(sys.argv[1])`,
    pdf,
  ]);
  await page.locator("input[type=file]").first().setInputFiles(pdf);
  await page
    .getByRole("combobox", { name: "نوع المحتوى", exact: true })
    .selectOption("textbook");
  const title = "إعادة صفحة واحدة — اختبار غير رسمي";
  await page.getByLabel("العنوان", { exact: true }).fill(title);
  await page
    .getByRole("checkbox", {
      name: "الشعب المستهدفة: علوم تجريبية",
      exact: true,
    })
    .check();
  await page.getByLabel("المادة", { exact: true }).selectOption("physics");
  await page.getByRole("button", { name: "رفع للمراجعة — ليس للنشر" }).click();
  await expect(
    page.getByText("مراجعة النسخة 1", { exact: true }),
  ).toBeVisible();
  const docs = await (await page.request.get("/api/owner/documents")).json();
  const document = docs.items.find((d: any) => d.title === title);
  const oldId = document.versions[0].id;
  await page.getByRole("button", { name: "بدء المعالجة", exact: true }).click();
  await expect(
    page.getByRole("button", { name: /^ص 2 · SUCCESS/ }),
  ).toBeVisible({ timeout: 30000 });
  await page.getByRole("button", { name: /^ص 2 · SUCCESS/ }).click();
  await expect(page.getByAltText("صفحة المصدر الأصلية")).toBeVisible();
  await page
    .getByRole("button", { name: "إعادة استخراج ص 2", exact: true })
    .click();
  await expect(
    page.getByRole("group", { name: "تأكيد إعادة استخراج الصفحة" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "إلغاء إعادة الاستخراج" }).click();
  expect(requests).toEqual([]); // Preview and cancel must not request Vision.
  await page
    .getByLabel("راجعت المصدر وأقرّ بتحذيرات الجودة الظاهرة إن وجدت.")
    .check();
  await page
    .getByLabel("ملاحظات المراجعة")
    .fill(
      "Synthetic two-page fixture reviewed. No live provider or official curriculum.",
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
  const before = await (
    await page.request.get(`/api/owner/versions/${oldId}/page/2`)
  ).json();
  expect(before.immutable_preview).toBe(true);
  await page
    .getByRole("button", { name: "إعادة استخراج ص 2", exact: true })
    .click();
  const confirm = page.getByRole("group", {
    name: "تأكيد إعادة استخراج الصفحة",
  });
  await expect(confirm).toContainText("سننشئ مسودة نسخة جديدة أولًا");
  await confirm.scrollIntoViewIfNeeded();
  await assertNoOverflow(page);
  await snapshot(page, "owner-reextract-confirm-desktop");
  await page.setViewportSize({ width: 390, height: 844 });
  await confirm.scrollIntoViewIfNeeded();
  await assertNoOverflow(page);
  await snapshot(page, "owner-reextract-confirm-mobile");
  const response = page.waitForResponse(
    (r) =>
      r.request().method() === "POST" && r.url().endsWith("/page/2/reextract"),
  );
  await page
    .getByRole("button", { name: "تأكيد إعادة استخراج ص 2", exact: true })
    .click();
  const res = await response;
  expect(res.status()).toBe(200);
  const queued = await res.json();
  expect(queued.scheduled).toBe(1);
  expect(queued.version_id).not.toBe(oldId);
  expect(queued.file_id).toBe(queued.version_id + ":primary");
  expect(requests).toHaveLength(1);
  await expect(
    page.getByText("مراجعة النسخة 2", { exact: true }),
  ).toBeVisible();
  await expect
    .poll(
      async () =>
        (
          await (
            await page.request.get(`/api/owner/versions/${queued.version_id}`)
          ).json()
        ).extraction_status,
      { timeout: 30000 },
    )
    .toMatch(/^COMPLETED/);
  await expect(
    page.getByRole("button", { name: "إعادة استخراج ص 2", exact: true }),
  ).toBeEnabled();
  await expect(page.locator(".review-grid pre")).toContainText("الحرارة");
  await expect(
    page.getByLabel("راجعت المصدر وأقرّ بتحذيرات الجودة الظاهرة إن وجدت."),
  ).not.toBeChecked();
  const unchanged = await (
    await page.request.get(`/api/owner/versions/${oldId}/page/2`)
  ).json();
  expect(unchanged).toEqual(before);
  const current = (
    await (await page.request.get("/api/owner/documents")).json()
  ).items.find((d: any) => d.id === document.id);
  expect(current.published_version).toBe(oldId);
  expect(current.versions).toHaveLength(2);
  await page.locator(".page-reextract-control").scrollIntoViewIfNeeded();
  await snapshot(page, "owner-reextract-result-mobile");
  await assertNoOverflow(page);
  await page
    .getByLabel("راجعت المصدر وأقرّ بتحذيرات الجودة الظاهرة إن وجدت.")
    .check();
  await page
    .getByLabel("ملاحظات المراجعة")
    .fill("Fresh page result reviewed in the explicit offline fixture.");
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
  expect(
    (await (await page.request.get("/api/owner/documents")).json()).items.find(
      (d: any) => d.id === document.id,
    ).published_version,
  ).toBe(queued.version_id);
  expect(errors).toEqual([]);
});
