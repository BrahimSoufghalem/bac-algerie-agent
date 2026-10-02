import { test, expect, Page } from "@playwright/test";
import { navigate, snapshot, assertNoOverflow } from "./helpers";

async function signIn(page: Page) {
  await page.goto("/");
  await page.getByLabel("البريد الإلكتروني").fill("teacher@test.invalid");
  await page.getByLabel("كلمة المرور").fill("Test-learning-password-1");
  await page.getByRole("button", { name: "دخول", exact: true }).click();
  await navigate(page, "＋ محادثة جديدة");
}
async function composerFits(page: Page) {
  const box = await page.locator(".composer").boundingBox();
  const viewport = page.viewportSize()!;
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width);
  expect(box!.y).toBeGreaterThanOrEqual(55);
  expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height);
  await assertNoOverflow(page);
}

test("conversation redesign: clean navigation, theme persistence, rail, mobile keyboard, real rename/delete", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await signIn(page);
  await expect(
    page.getByRole("heading", { name: "ما الذي نحضّره اليوم؟" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "أمان الحساب", exact: true }),
  ).not.toBeVisible();
  await composerFits(page);
  await snapshot(page, "redesign-empty-light-desktop");
  await page.getByRole("button", { name: "راجع شرحي", exact: true }).click();
  await expect(page.getByLabel("رسالتك")).toHaveValue(
    "راجع شرحًا أعددته للطلاب",
  );
  await expect(page.getByLabel("رسالتك")).toBeFocused();
  await page.getByLabel("رسالتك").fill("");
  await page
    .getByRole("button", { name: "إعدادات الحساب", exact: true })
    .click();
  await page.getByRole("button", { name: "مظهر داكن", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.keyboard.press("Escape");
  await expect(page.locator(".account-panel")).not.toBeVisible();
  await snapshot(page, "redesign-empty-dark-desktop");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page
    .getByRole("button", { name: "طي الشريط الجانبي", exact: true })
    .click();
  await expect(page.locator(".sidebar")).toHaveCSS("width", "64px");
  await page.reload();
  await expect(page.locator(".app")).toHaveClass(/sidebar-collapsed/);
  await page
    .getByRole("button", { name: "توسيع الشريط الجانبي", exact: true })
    .click();
  await page.locator(".history-item.selected summary").click();
  await page.getByRole("button", { name: "إعادة تسمية", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "إعادة تسمية المحادثة" });
  await expect(dialog.getByLabel("عنوان المحادثة")).toBeFocused();
  await dialog.getByLabel("عنوان المحادثة").fill("مسار تصميم اختباري");
  await dialog.getByRole("button", { name: "حفظ العنوان" }).click();
  await expect(page.locator(".history-item.selected > button")).toHaveText(
    "مسار تصميم اختباري",
  );
  await page.reload();
  await expect(page.locator(".history-item.selected > button")).toHaveText(
    "مسار تصميم اختباري",
  );
  await page.locator(".history-item.selected summary").click();
  await page.getByRole("button", { name: "حذف", exact: true }).click();
  await page.getByRole("button", { name: "حذف نهائيًا" }).click();
  await expect(
    page.locator(".history-item > button", { hasText: "مسار تصميم اختباري" }),
  ).toHaveCount(0);
  for (const width of [768, 390, 360]) {
    await page.setViewportSize({ width, height: 844 });
    await composerFits(page);
    await snapshot(page, `redesign-empty-dark-${width}`);
  }
  await page.getByRole("button", { name: "فتح القائمة" }).click();
  await expect(page.locator(".workspace")).toHaveAttribute("inert", "");
  await page.keyboard.press("Shift+Tab");
  expect(
    await page.evaluate(() => !!document.activeElement?.closest(".sidebar")),
  ).toBe(true);
  await snapshot(page, "redesign-menu-dark-mobile");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "فتح القائمة" })).toBeFocused();
  await page.getByRole("button", { name: "فتح القائمة" }).click();
  await page
    .getByRole("button", { name: "إعدادات الحساب", exact: true })
    .click();
  await page.getByRole("button", { name: "مظهر تلقائي", exact: true }).click();
  await page.emulateMedia({ colorScheme: "light" });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("button", { name: "مظهر فاتح", exact: true }).click();
  await page.getByRole("button", { name: "إغلاق القائمة" }).click();
  await snapshot(page, "redesign-empty-light-mobile");
  expect(errors).toEqual([]);
});

test("new chat creation: a slow response cannot erase a draft typed after the click", async ({
  page,
}) => {
  await signIn(page);
  await expect(page.locator(".history-item.selected")).toHaveCount(1);
  await page.route("**/api/conversations", async (route) => {
    if (route.request().method() === "POST")
      await new Promise((resolve) => setTimeout(resolve, 500));
    await route.continue();
  });
  await page
    .getByRole("button", { name: "＋ محادثة جديدة", exact: true })
    .click();
  await page.getByLabel("رسالتك").fill("مسودة أثناء إنشاء المحادثة");
  await expect(
    page.getByRole("button", { name: "إرسال ↑", exact: true }),
  ).toBeEnabled();
  await expect(page.getByLabel("رسالتك")).toHaveValue(
    "مسودة أثناء إنشاء المحادثة",
  );
  expect(
    (
      await (
        await page.request.get(
          `/api/conversations/${new URL(page.url()).hash.slice(6)}`,
        )
      ).json()
    ).messages,
  ).toHaveLength(0);
});

test("composer: attachment preserves draft, deletion cannot send, IME Enter and multiline remain safe", async ({
  page,
}) => {
  await signIn(page);
  // Use a genuinely unbound composer; delete the newly created empty chat first.
  await page.locator(".history-item.selected summary").click();
  await page.getByRole("button", { name: "حذف", exact: true }).click();
  await page.getByRole("button", { name: "حذف نهائيًا" }).click();
  await expect(page.locator(".history-item.selected")).toHaveCount(0);
  const before = (await (await page.request.get("/api/conversations")).json())
    .items.length;
  const draft = "مسودة مهمة لا تُرسل عند إرفاق الملف أو حذفه";
  await page.getByLabel("رسالتك").fill(draft);
  await page
    .getByRole("button", {
      name: "إرفاق ملف خاص مؤقتًا · 24 ساعة",
      exact: true,
    })
    .click();
  await page.getByLabel("الملف الخاص", { exact: true }).setInputFiles({
    name: "private-draft.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Unindexed private attachment"),
  });
  await expect(page.locator(".private-file-row")).toContainText(
    "private-draft.txt",
  );
  await expect(page.getByLabel("رسالتك")).toHaveValue(draft);
  const chats = (await (await page.request.get("/api/conversations")).json())
    .items;
  expect(chats.length).toBe(before + 1);
  const id = new URL(page.url()).hash.slice(6);
  await page
    .getByRole("button", { name: "حذف الملف private-draft.txt", exact: true })
    .click();
  await expect(page.locator(".private-file-row")).toHaveCount(0);
  await expect(page.getByLabel("رسالتك")).toHaveValue(draft);
  expect(
    (await (await page.request.get(`/api/conversations/${id}`)).json())
      .messages,
  ).toHaveLength(0);
  await page.keyboard.press("Escape");
  const input = page.getByLabel("رسالتك");
  await input.focus();
  await input.dispatchEvent("keydown", {
    key: "Enter",
    code: "Enter",
    isComposing: true,
  });
  expect(
    (await (await page.request.get(`/api/conversations/${id}`)).json())
      .messages,
  ).toHaveLength(0);
  await input.press("Shift+Enter");
  await expect(input).toHaveValue(draft + "\n");
  await input.fill(
    Array.from({ length: 20 }, () => "سطر من مسودة طويلة").join("\n"),
  );
  expect((await input.boundingBox())!.height).toBeLessThanOrEqual(180);
  await page.setViewportSize({ width: 360, height: 640 });
  await composerFits(page);
});

test("real answer controls: copy, edit, smart scrolling, retry, source-safe scientific blocks, dark/mobile", async ({
  page,
  context,
}) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await signIn(page);
  await page.getByLabel("رسالتك").fill("أريد حساب علمي والتحقق والرسم منحنى");
  await page.getByRole("button", { name: "إرسال ↑", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "تفسير بعد الرسم" }),
  ).toBeVisible({ timeout: 30000 });
  await expect(page.locator(".verification")).toHaveCount(0);
  await expect(page.locator(".activity")).toHaveCount(0);
  await page
    .getByRole("button", { name: "نسخ الرد", exact: true })
    .last()
    .click();
  await expect(page.getByRole("button", { name: "تم نسخ الرد" })).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain(
    "حساب علمي",
  );
  await composerFits(page);
  await page
    .getByRole("button", { name: "إعدادات الحساب", exact: true })
    .click();
  await page.getByRole("button", { name: "مظهر داكن", exact: true }).click();
  await page.keyboard.press("Escape");
  // Scrolling upwards must not be overridden by a late image resize.
  await page.locator(".chat-scroll").evaluate((x) => {
    x.scrollTop = 0;
  });
  await expect(
    page.getByRole("button", { name: "العودة إلى أحدث رسالة" }),
  ).toBeVisible();
  await page
    .locator(".message-body")
    .last()
    .evaluate((x) => {
      x.style.paddingBottom = "80px";
    });
  await page.waitForTimeout(150);
  expect(await page.locator(".chat-scroll").evaluate((x) => x.scrollTop)).toBe(
    0,
  );
  await snapshot(page, "redesign-answer-dark-desktop");
  await page.getByRole("button", { name: "العودة إلى أحدث رسالة" }).click();
  await expect(
    page.getByRole("button", { name: "العودة إلى أحدث رسالة" }),
  ).not.toBeVisible();
  await page.getByRole("button", { name: "تعديل", exact: true }).last().click();
  await expect(page.getByLabel("رسالتك")).toBeFocused();
  await expect(page.getByLabel("رسالتك")).toHaveValue(
    "أريد حساب علمي والتحقق والرسم منحنى",
  );
  await page.getByRole("button", { name: "إلغاء التعديل" }).click();
  const rerun = page.waitForResponse(
    (r) => r.url().endsWith("/retry") && r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "إعادة محاولة الرسالة الأخيرة" })
    .click();
  const rerunResponse = await rerun;
  expect(rerunResponse.ok()).toBe(true);
  const { run_id: retryRun } = await rerunResponse.json();
  await expect
    .poll(
      async () => {
        const response = await page.request.get(`/api/runs/${retryRun}`);
        return (await response.json()).status;
      },
      { timeout: 30000 },
    )
    .toBe("COMPLETED");
  await expect(
    page.getByRole("button", { name: "إعادة محاولة الرسالة الأخيرة" }),
  ).toBeVisible({ timeout: 30000 });
  for (const width of [390, 360]) {
    await page.setViewportSize({ width, height: 844 });
    await composerFits(page);
    await page.locator(".chat-scroll").evaluate((x) => {
      x.scrollTop = 0;
    });
    await snapshot(page, `redesign-answer-dark-${width}`);
  }
});
