import { test, expect } from "@playwright/test";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { navigate, snapshot, assertNoOverflow } from "./helpers";

test("owner selects several target tracks for one book and edits the same draft", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.getByLabel("البريد الإلكتروني").fill("owner@test.invalid");
  await page.getByLabel("كلمة المرور").fill("Test-password-only-1");
  await page.getByRole("button", { name: "دخول", exact: true }).click();
  await navigate(page, "▥ إدارة المحتوى");
  const branch = (label: string) =>
    page.getByRole("checkbox", {
      name: "الشعب المستهدفة: " + label,
      exact: true,
    });
  await branch("علوم تجريبية").check();
  await branch("رياضيات").check();
  await page.getByLabel("المادة", { exact: true }).selectOption("physics");
  await branch("لغات أجنبية").check();
  await expect(page.getByLabel("المادة", { exact: true })).toHaveValue("");
  await expect(
    page.getByLabel("المادة", { exact: true }).locator("option[value=physics]"),
  ).toHaveCount(0);
  await branch("لغات أجنبية").uncheck();
  await page.getByLabel("المادة", { exact: true }).selectOption("physics");
  const file = path.join(process.env.TEST_DATA_DIR!, "shared-schoolbook.pdf");
  execFileSync(process.env.BAC_PYTHON || "python", [
    "tests/fixture_book.py",
    file,
  ]);
  await page.getByLabel("اختر ملف PDF", { exact: true }).setInputFiles(file);
  await page
    .getByLabel("العنوان", { exact: true })
    .fill("كتاب مشترك — اختبار محلي");
  await snapshot(page, "multi-track-owner-desktop");
  await page.setViewportSize({ width: 390, height: 844 });
  await assertNoOverflow(page);
  await snapshot(page, "multi-track-owner-mobile");
  await page.setViewportSize({ width: 1440, height: 1000 });
  const uploaded = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/owner/documents/upload") &&
      r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "رفع للمراجعة — ليس للنشر" }).click();
  const result = await (await uploaded).json();
  const version = await (
    await page.request.get("/api/owner/versions/" + result.version_id)
  ).json();
  expect(version.metadata.tracks).toEqual([
    "experimental_sciences",
    "mathematics",
  ]);
  expect(version.files).toHaveLength(1);
  const row = page.locator(".document-row").filter({
    has: page.getByRole("heading", {
      name: "كتاب مشترك — اختبار محلي",
      exact: true,
    }),
  });
  await expect(row).toContainText("علوم تجريبية، رياضيات");
  await page.getByText("تعديل هوية المسودة", { exact: true }).click();
  await page
    .getByRole("checkbox", { name: "شعب المسودة: تقني رياضي", exact: true })
    .check();
  await page
    .getByRole("button", { name: "حفظ هوية المسودة", exact: true })
    .click();
  await expect
    .poll(
      async () =>
        (
          await (
            await page.request.get("/api/owner/versions/" + result.version_id)
          ).json()
        ).metadata.tracks,
    )
    .toEqual(["experimental_sciences", "mathematics", "technical_mathematics"]);
  expect(errors).toEqual([]);
});
