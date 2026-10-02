import { test, expect } from "@playwright/test";
import { navigate, snapshot, assertNoOverflow } from "./helpers";

test("failed read attempt remains distinct after retry, actual cache reload and corrected graph", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.getByLabel("البريد الإلكتروني").fill("work-ui@test.invalid");
  await page.getByLabel("كلمة المرور").fill("Test-learning-password-1");
  await page.getByRole("button", { name: "دخول", exact: true }).click();
  await navigate(page, "＋ محادثة جديدة");
  await page.getByLabel("رسالتك").fill("اختبار مرجع ومحاولات: اشرح درس القذف");
  await page.getByRole("button", { name: "إرسال ↑", exact: true }).click();
  const retry = page.getByRole("button", {
    name: "إعادة المحاولة",
    exact: true,
  });
  await expect(retry).toBeVisible({ timeout: 30000 });
  const failed = page.locator(".work-disclosure").first();
  const failedRun = await failed.getAttribute("data-run");
  await failed.getByRole("button").click();
  const failedText = await failed.locator(".work-timeline").innerText();
  expect(failedText).toContain("مراجعة المعلومات");
  expect(failedText).toContain("تعذّر إكمال الرد");
  await retry.click();
  await expect(
    page.getByRole("heading", { name: "رد بعد إعادة المحاولة" }),
  ).toBeVisible({ timeout: 30000 });
  const previous = page.locator(".historical-work .work-disclosure");
  await expect(previous).toHaveCount(1);
  await expect(previous).toHaveAttribute("data-run", failedRun!);
  expect(await previous.locator(".work-timeline").innerText()).toBe(failedText);
  const current = page.locator(
    ".message.assistant:has(.message-body) .work-disclosure",
  );
  await current.first().getByRole("button").click();
  await expect(current.first().locator(".work-timeline")).toContainText(
    "مراجعة المعلومات السابقة",
  );
  await page
    .getByLabel("رسالتك")
    .fill("اختبار مرجع ومحاولات: رسم السرعة في درس القذف");
  await page.getByRole("button", { name: "إرسال ↑", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "رسم بعد التصحيح" }),
  ).toBeVisible({ timeout: 30000 });
  await expect(page.locator(".scientific-chart svg")).toBeVisible();
  await current.last().getByRole("button").click();
  const plotStages = current
    .last()
    .locator(".work-timeline li")
    .filter({ hasText: "إعداد رسم توضيحي" });
  await expect(plotStages).toHaveCount(2);
  await expect(plotStages.first()).toHaveAttribute("data-state", "unavailable");
  await expect(plotStages.last()).toHaveAttribute("data-state", "done");
  await expect(previous).toHaveAttribute("data-run", failedRun!);
  await current.last().scrollIntoViewIfNeeded();
  await snapshot(page, "grounded-graph-correction-desktop");
  await page.reload();
  await expect(page.locator(".work-disclosure")).toHaveCount(3);
  await expect(previous).toHaveAttribute("data-run", failedRun!);
  await current.last().getByRole("button").click();
  await page.setViewportSize({ width: 390, height: 844 });
  await current.last().scrollIntoViewIfNeeded();
  await assertNoOverflow(page);
  await snapshot(page, "grounded-graph-correction-mobile");
  expect(errors).toEqual([]);
});
