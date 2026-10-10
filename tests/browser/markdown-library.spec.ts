import { test, expect } from "@playwright/test";
import { navigate, snapshot, assertNoOverflow } from "./helpers";
import { signIn, add, publish } from "./markdown-helpers";

test("Markdown import, explicit review, inventory and desktop/mobile/dark QA", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await signIn(page);
  await expect(
    page.getByRole("heading", { name: "ملفاتك، بوضوح." }),
  ).toBeVisible();
  await expect(page.getByRole("table").getByRole("row")).toHaveCount(11);
  await snapshot(page, "markdown-inventory-desktop");
  await add(page, "ملف المكثفة — اختبار واجهة");
  await page.getByText("شحن المكثفة", { exact: true }).first().click();
  await expect(page.locator(".markdown-source .katex")).toHaveCount(1);
  await snapshot(page, "markdown-preview-desktop");
  await publish(page);
  const row = page.getByRole("row").filter({
    has: page.getByRole("rowheader", {
      name: "العلوم الفيزيائية",
      exact: true,
    }),
  });
  await expect(row.getByText("مضافة", { exact: true }).first()).toBeVisible();
  await assertNoOverflow(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await snapshot(page, "markdown-inventory-mobile");
  await assertNoOverflow(page);
  await page.evaluate(() =>
    document.documentElement.setAttribute("data-theme", "dark"),
  );
  await snapshot(page, "markdown-inventory-dark-mobile");
  expect(errors).toEqual([]);
});

test("scoped deletion can cancel, preserves shared file, and global deletion preserves subject", async ({
  page,
}) => {
  const removals: { track: string | null; category: string | null }[] = [];
  page.on("request", (r) => {
    if (
      r.method() === "POST" &&
      r.url().endsWith("/api/owner/library/remove")
    ) {
      const b = r.postDataJSON();
      removals.push({ track: b.track, category: b.content_type });
    }
  });

  await signIn(page);
  await add(page, "ملف مشترك للحذف — QA", "exercises", [
    "علوم تجريبية",
    "رياضيات",
  ]);
  await publish(page);
  await page
    .getByRole("button", { name: "حذف محتوى العلوم الفيزيائية", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByLabel("نوع المحتوى", { exact: true })
    .selectOption("exercises");
  await expect(
    page.getByText("ملف مشترك للحذف — QA", { exact: true }).last(),
  ).toBeVisible();
  await expect(
    page.getByRole("dialog").getByLabel("نوع المحتوى", { exact: true }),
  ).toHaveValue("exercises");
  await snapshot(page, "markdown-delete-confirmation");
  await expect(
    page.getByRole("button", { name: "حذف المحتوى المحدد", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "إلغاء", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page
    .getByRole("button", { name: "حذف محتوى العلوم الفيزيائية", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByLabel("نوع المحتوى", { exact: true })
    .selectOption("exercises");
  await page.getByLabel("أؤكد حذف المحتوى المحدد.", { exact: false }).check();
  await page
    .getByRole("button", { name: "حذف المحتوى المحدد", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(removals).toEqual([
    { track: "experimental_sciences", category: "exercises" },
  ]);
  const docs = (await (await page.request.get("/api/owner/documents")).json())
    .items;
  expect(docs.some((d: any) => d.title === "الحرارة — مصدر محلي")).toBe(true);
  await page.getByLabel("الشعبة", { exact: true }).selectOption("mathematics");
  await expect(
    page.getByText("ملف مشترك للحذف — QA", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "حذف محتوى العلوم الفيزيائية", exact: true })
    .click();
  await page.getByRole("dialog").getByLabel("نطاق الحذف").selectOption("all");
  await page
    .getByRole("dialog")
    .getByLabel("نوع المحتوى", { exact: true })
    .selectOption("exercises");
  await page.getByLabel("أؤكد حذف المحتوى المحدد.", { exact: false }).check();
  await page
    .getByRole("button", { name: "حذف المحتوى المحدد", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(removals[1]).toEqual({ track: null, category: "exercises" });
  const row = page.getByRole("row").filter({
    has: page.getByRole("rowheader", {
      name: "العلوم الفيزيائية",
      exact: true,
    }),
  });
  await expect(row).toBeVisible();
  await expect(row.getByText("لم تُضف", { exact: true })).toHaveCount(4);
});

test("model setup has no extraction slot and source upload refuses PDF", async ({
  page,
}) => {
  await signIn(page);
  await navigate(page, "⚙ إعداد النماذج");
  await expect(
    page
      .getByLabel("الاستخدام", { exact: true })
      .locator('option[value="extraction"]'),
  ).toHaveCount(0);
  await navigate(page, "▥ إدارة المحتوى");
  const csrf = (await (await page.request.get("/api/auth/me")).json()).csrf;
  const result = await page.request.post("/api/owner/documents/upload", {
    headers: { "X-CSRF-Token": csrf },
    multipart: {
      metadata: JSON.stringify({
        kind: "book",
        subject: "physics",
        track: "science",
      }),
      file: {
        name: "bad.pdf",
        mimeType: "application/pdf",
        buffer: Buffer.from("%PDF fake"),
      },
    },
  });
  expect(result.status()).toBe(422);
});

test("cancel invalidates a delayed deletion preview without reopening the dialog", async ({
  page,
}) => {
  await signIn(page);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/owner/library/remove-preview", async (route) => {
    if (route.request().postDataJSON().content_type === "exercises") await gate;
    await route.continue();
  });
  await page
    .getByRole("button", { name: "حذف محتوى العلوم الفيزيائية", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  const requested = page.waitForRequest(
    (r) =>
      r.url().endsWith("/api/owner/library/remove-preview") &&
      r.postDataJSON().content_type === "exercises",
  );
  await page
    .getByRole("dialog")
    .getByLabel("نوع المحتوى", { exact: true })
    .selectOption("exercises");
  await requested;
  await expect(
    page.getByRole("button", { name: "حذف المحتوى المحدد", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "إلغاء", exact: true }).click();
  const response = page.waitForResponse((r) =>
    r.url().endsWith("/api/owner/library/remove-preview"),
  );
  release();
  await response;
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    page.getByRole("button", {
      name: "حذف محتوى العلوم الفيزيائية",
      exact: true,
    }),
  ).toBeEnabled();
});
