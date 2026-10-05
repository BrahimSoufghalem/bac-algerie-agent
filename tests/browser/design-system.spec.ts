import { test, expect, Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { navigate, snapshot, assertNoOverflow, chooseSubject } from "./helpers";
async function signIn(
  page: Page,
  email = "design-owner@test.invalid",
  password = "Test-design-password-1",
) {
  await page.goto("/");
  await page.getByLabel("البريد الإلكتروني").fill(email);
  await page.getByLabel("كلمة المرور").fill(password);
  await page.getByRole("button", { name: "دخول", exact: true }).click();
  await expect(page.locator(".workspace")).toBeVisible();
}
async function audit(page: Page, name: string) {
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all(
      document
        .getAnimations()
        .filter((a) => a.effect?.getTiming().iterations !== Infinity)
        .map((a) => a.finished.catch(() => {})),
    );
  });
  await assertNoOverflow(page);
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(
    result.violations.map((v) => ({
      id: v.id,
      nodes: v.nodes.map((n) => ({
        target: n.target,
        summary: n.failureSummary,
      })),
    })),
    name,
  ).toEqual([]);
}
async function previewPair(page: Page, name: string) {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await audit(page, name + " desktop");
  await snapshot(page, "identity-" + name + "-desktop");
  await page.setViewportSize({ width: 390, height: 844 });
  await audit(page, name + " mobile");
  await snapshot(page, "identity-" + name + "-mobile");
  await page.setViewportSize({ width: 1440, height: 1000 });
}
test("Masar identity: real admin workspaces, WCAG AA checks, dark mode and responsive controls", async ({
  page,
}) => {
  test.setTimeout(180000);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await previewPair(page, "login");
  await page
    .getByRole("button", { name: "ليس لديك حساب؟ أنشئ حساب طالب", exact: true })
    .click();
  await audit(page, "register");
  await snapshot(page, "identity-register-desktop");
  await page
    .getByRole("button", { name: "لديك حساب؟ سجّل الدخول", exact: true })
    .click();
  await signIn(page);
  for (const [nav, name] of [
    ["▥ إدارة المحتوى", "library"],
    ["⚙ إعداد النماذج", "models"],
    ["الحسابات والحدود", "accounts"],
    ["◷ الاستخدام", "usage"],
    ["تفضيلات وخصوصية", "preferences"],
    ["ملاحظات مسار التعليمية", "notes"],
    ["أمان الحساب", "security"],
    ["استخدامي وحدودي", "personal-usage"],
  ]) {
    await navigate(page, nav);
    await expect(page.locator(".page-content h1")).toBeVisible();
    await previewPair(page, name);
    if (name === "library")
      expect(
        (await page.locator(".source-tracks").first().boundingBox())!.width,
      ).toBeGreaterThan(300);
  }
  await navigate(page, "＋ محادثة جديدة");
  await page
    .getByRole("button", { name: "إعدادات الحساب", exact: true })
    .click();
  await page.getByRole("button", { name: "مظهر داكن", exact: true }).click();
  await page.keyboard.press("Escape");
  await previewPair(page, "chat-dark");
  await navigate(page, "▥ إدارة المحتوى");
  await previewPair(page, "library-dark");
  await navigate(page, "＋ محادثة جديدة");
  await page.locator(".history-item.selected summary").click();
  await page.getByRole("button", { name: "حذف", exact: true }).click();
  await audit(page, "delete dialog dark");
  await snapshot(page, "identity-delete-dialog-dark");
  await page.keyboard.press("Escape");
  expect(errors).toEqual([]);
});
test("subject Radix listbox and dialog: RTL, keyboard, Escape, focus return, reduced motion", async ({
  page,
}) => {
  test.setTimeout(90000);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await signIn(page, "practice@test.invalid", "Test-learning-password-1");
  await chooseSubject(page, "physics");
  const picker = page.getByRole("combobox", {
    name: "مادة المحادثة",
    exact: true,
  });
  await picker.focus();
  await picker.press("ArrowDown");
  await expect(page.getByRole("listbox")).toBeVisible();
  await audit(page, "subject menu");
  await snapshot(page, "identity-subject-menu-desktop");
  await page.keyboard.press("Escape");
  await expect(picker).toBeFocused();
  await page.setViewportSize({ width: 390, height: 844 });
  await picker.click();
  await assertNoOverflow(page);
  await snapshot(page, "identity-subject-menu-mobile");
  await page.keyboard.press("Escape");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await navigate(page, "＋ محادثة جديدة");
  await page.locator(".history-item.selected summary").click();
  await page.getByRole("button", { name: "إعادة تسمية", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "إعادة تسمية المحادثة" });
  await expect(dialog.getByLabel("عنوان المحادثة")).toBeFocused();
  await audit(page, "dialog");
  await snapshot(page, "identity-dialog-desktop");
  await page.setViewportSize({ width: 390, height: 844 });
  await snapshot(page, "identity-dialog-mobile");
  for (let i = 0; i < 8; i++) {
    await page.keyboard.press("Tab");
    expect(
      await page.evaluate(
        () => !!document.activeElement?.closest('[role="dialog"]'),
      ),
    ).toBe(true);
  }
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "فتح القائمة", exact: true }),
  ).toBeFocused();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.locator(".history-item.selected summary").click();
  await page.getByRole("button", { name: "إعادة تسمية", exact: true }).click();
  await page.keyboard.press("Escape");
  await expect(page.locator(".history-item.selected summary")).toBeFocused();
  expect(
    await page
      .locator(".profile-button")
      .evaluate((el) => getComputedStyle(el).transitionDuration),
  ).toBe("0s");
});

test("tablet drawer retains owner navigation after desktop rail collapse", async ({
  page,
}) => {
  await signIn(page);
  await page
    .getByRole("button", { name: "طي الشريط الجانبي", exact: true })
    .click();
  await page.setViewportSize({ width: 740, height: 900 });
  await page.getByRole("button", { name: "فتح القائمة", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "▥ إدارة المحتوى", exact: true }),
  ).toBeVisible();
  await snapshot(page, "identity-tablet-drawer");
  await page
    .getByRole("button", { name: "▥ إدارة المحتوى", exact: true })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "من المصدر إلى نسخة معتمدة",
      exact: true,
    }),
  ).toBeVisible();
  await assertNoOverflow(page);
  await navigate(page, "أمان الحساب");
  const checkbox = page.getByRole("checkbox");
  expect((await checkbox.boundingBox())!.width).toBe(18);
  expect((await checkbox.boundingBox())!.height).toBe(18);
});
