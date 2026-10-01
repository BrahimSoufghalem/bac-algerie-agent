import { test, expect, Page } from "@playwright/test";
import { mkdir, writeFile, readFile } from "node:fs/promises";
import path from "node:path";
import { execFileSync } from "node:child_process";
const qa = path.resolve("browser-results/previews");
async function snapshot(page: Page, name: string) {
  await page.evaluate(() => document.fonts.ready);
  const html = await page.evaluate(async () => {
    const clone = document.documentElement.cloneNode(true) as HTMLElement;
    clone
      .querySelectorAll("script,link[rel=modulepreload]")
      .forEach((x) => x.remove());
    clone.querySelectorAll("link[href]").forEach((x) => {
      const href = x.getAttribute("href") || "";
      if (href.startsWith("/assets/"))
        x.setAttribute("href", location.origin + href);
    });
    for (const img of clone.querySelectorAll("img")) {
      const src = img.getAttribute("src");
      if (!src || src.startsWith("data:")) continue;
      const res = await fetch(src);
      const blob = await res.blob();
      const data = await new Promise<string>((resolve) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result as string);
        reader.readAsDataURL(blob);
      });
      img.setAttribute("src", data);
    }
    const s = document.createElement("style");
    s.textContent =
      ".workspace{max-height:none;overflow:visible}.composer-wrap{position:static}.sidebar{position:fixed;inset-inline-start:0}.workspace{margin-inline-start:268px}@media(max-width:700px){.workspace{margin-inline-start:0}}";
    clone.querySelector("head")?.appendChild(s);
    return "<!doctype html>" + clone.outerHTML;
  });
  await mkdir(qa, { recursive: true });
  let offline = html;
  for (const link of [...html.matchAll(/<link[^>]*rel="stylesheet"[^>]*>/g)]) {
    const href = link[0].match(/href="([^"]+)"/);
    if (!href) continue;
    const cssFile = path.join(
      process.cwd(),
      "dist/assets",
      path.basename(href[1]),
    );
    let css = await readFile(cssFile, "utf8");
    css = css.replace(
      /url\(([^)]+)\)/g,
      (_, url) =>
        'url("file://' +
        path.join(
          process.cwd(),
          "dist/assets",
          path.basename(url.replace(/["']/g, "")),
        ) +
        '")',
    );
    offline = offline.replace(link[0], "<style>" + css + "</style>");
  }
  await writeFile(path.join(qa, name + ".html"), offline);
}
async function assertNoOverflow(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
  ).toBe(true);
}
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
    page.getByRole("button", { name: "▥ إدارة المحتوى" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "⚙ إعداد النماذج" }).click();
  await expect(page.getByLabel("Model", { exact: true })).toHaveValue(
    "offline-test-fixture",
  );
  await snapshot(page, "models-desktop");
  await page.getByRole("button", { name: "▥ إدارة المحتوى" }).click();
  const pdf = path.join(process.env.TEST_DATA_DIR!, "scanned_book.pdf");
  execFileSync(process.env.BAC_PYTHON || "python", [
    "tests/fixture_book.py",
    pdf,
  ]);
  await page.locator("input[type=file]").setInputFiles(pdf);
  await page
    .getByLabel("العنوان", { exact: true })
    .fill("مبادئ الحرارة — مصدر اختبار");
  await page.getByLabel("المادة", { exact: true }).fill("فيزياء");
  await page.getByLabel("التخصص", { exact: true }).fill("علوم تجريبية");
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
  ).toHaveLength(0);
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
    page.getByRole("button", { name: "نشر للطلاب", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "نشر للطلاب", exact: true }).click();
  await expect
    .poll(
      async () =>
        (await (await page.request.get("/api/library/documents")).json()).items
          .length,
    )
    .toBe(1);
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
  await expect(
    student.getByRole("heading", { name: "أين توقفتَ في الدرس؟" }),
  ).toBeVisible();
  await snapshot(student, "chat-empty-desktop");
  expect((await student.request.get("/api/owner/documents")).status()).toBe(
    403,
  );
  await student
    .getByRole("textbox", { name: "رسالتك" })
    .fill("اشرح درس الحرارة من المكتبة مع صورة المصدر والمعادلة.");
  await student.getByRole("button", { name: "إرسال ↑", exact: true }).click();
  await expect(
    student.getByRole("heading", { name: "الحرارة وانتقال الطاقة" }),
  ).toBeVisible({ timeout: 20000 });
  await expect(student.locator(".sources button")).toHaveCount(1);
  await expect(student.locator(".katex-display")).toHaveCount(1);
  await expect(student.locator(".message.assistant figure img")).toBeVisible();
  await snapshot(student, "chat-answer-desktop");
  await assertNoOverflow(student);
  await student.reload();
  await expect(
    student.getByRole("heading", { name: "الحرارة وانتقال الطاقة" }),
  ).toBeVisible();
  await student.locator(".sources button").click();
  await expect(student.getByRole("dialog")).toBeVisible();
  await snapshot(student, "source-desktop");
  await student.getByRole("button", { name: "إغلاق المصدر" }).click();
  await student.setViewportSize({ width: 390, height: 844 });
  await assertNoOverflow(student);
  await snapshot(student, "chat-answer-mobile");
  await student.getByRole("button", { name: "فتح القائمة" }).click();
  await snapshot(student, "menu-mobile");
  await student.getByRole("button", { name: "إغلاق القائمة" }).click();
  await expect(student.locator(".sidebar")).not.toBeVisible();
  await student.getByRole("button", { name: "فتح القائمة" }).click();
  await student.getByRole("button", { name: "▤ المكتبة المنشورة" }).click();
  await expect(
    student.getByRole("heading", { name: "مصادر جاهزة للتعلّم" }),
  ).toBeVisible();
  await student.getByRole("button", { name: "استكشف الفهرس" }).click();
  await expect(student.getByRole("dialog")).toBeVisible();
  await assertNoOverflow(student);
  await snapshot(student, "library-mobile");
  await page.getByRole("button", { name: "◷ الاستخدام" }).click();
  await expect(
    page.getByRole("heading", { name: "استخدام معلَن، لا تقديرات وهمية" }),
  ).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "offline-test-fixture", exact: true }),
  ).toBeVisible();
  await snapshot(page, "usage-desktop");
  await page.getByRole("button", { name: "▥ إدارة المحتوى" }).click();
  await page.getByRole("button", { name: "نسخة 1 · PUBLISHED" }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await snapshot(page, "owner-mobile");
  await assertNoOverflow(page);
  expect(errors).toEqual([]);
  await ctx.close();
});
