import { test, expect } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { snapshot, assertNoOverflow } from "./helpers";
for (const mode of ["line", "bar", "scatter"])
  test(`${mode}: real scientific tools → failed and passed evidence → interactive chart → explanation → reload/mobile`, async ({
    page,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto("/");
    await page
      .getByLabel("البريد الإلكتروني")
      .fill(`science-${mode}@test.invalid`);
    await page.getByLabel("كلمة المرور").fill("Test-science-password-1");
    await page.getByRole("button", { name: "دخول", exact: true }).click();
    await page
      .getByRole("textbox", { name: "رسالتك" })
      .fill(
        `أريد حساب علمي والتحقق والرسم ${mode === "bar" ? "أعمدة" : mode === "scatter" ? "نقاط" : "منحنى"}، مع عرض الفحص الذي لم ينجح.`,
      );
    await page.getByRole("button", { name: "إرسال ↑", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "تفسير بعد الرسم" }),
    ).toBeVisible({ timeout: 30000 });
    await expect(page.locator(".verification.failed")).toContainText(
      "لم ينجح الفحص",
    );
    await expect(page.locator(".verification.passed")).toContainText(
      "نجح الفحص المحدد",
    );
    await expect(
      page.locator(".scientific-chart:not(.scientific-diagram) svg"),
    ).toBeVisible();
    await expect(page.locator(".scientific-diagram svg")).toBeVisible();
    await expect(page.locator(".scientific-diagram")).toContainText(
      "ليس صورة مصدر",
    );
    await expect(
      page.locator(".scientific-chart:not(.scientific-diagram)"),
    ).toContainText("من المخرجات المحسوبة مباشرة");
    const order = await page
      .locator(".message.assistant .message-body")
      .evaluate((el) =>
        [...el.children].map((x) => x.tagName + ":" + x.className),
      );
    expect(order.findIndex((x) => x.includes("scientific-chart"))).toBeLessThan(
      order.findIndex((x) => x === "H3:"),
    );
    await page.getByRole("slider", { name: "النقطة المعروضة" }).fill("20");
    await expect(page.locator(".chart-readout")).toContainText(
      "x = 2 · y = 10",
    );
    await page
      .getByText("اعرض القيم وبيانات المصدر الحسابي", { exact: true })
      .click();
    await expect(page.locator(".chart-data tbody tr")).toHaveCount(21);
    await assertNoOverflow(page);
    await mkdir("browser-results/science-qa", { recursive: true });
    await snapshot(page, `science-${mode}-desktop`);
    await page
      .locator(".scientific-chart:not(.scientific-diagram)")
      .screenshot({
        path: `browser-results/science-qa/chart-${mode}-desktop.png`,
      });
    const docs = await (await page.request.get("/api/conversations")).json();
    const chat =
      docs.items.find((x: any) => x.title.includes("حساب علمي")) ||
      docs.items[0];
    const messages = await (
      await page.request.get("/api/conversations/" + chat.id)
    ).json();
    const verification = messages.messages
      .at(-1)
      .blocks.find((x: any) => x.type === "verification");
    const evidence = await (
      await page.request.get("/api/science/results/" + verification.result_id)
    ).json();
    expect(evidence.output.status).toBe("failed");
    await page.reload();
    await expect(
      page.locator(".scientific-chart:not(.scientific-diagram) svg"),
    ).toBeVisible();
    await expect(page.locator(".verification.failed")).toContainText(
      "لم ينجح الفحص",
    );
    await page.setViewportSize({ width: 390, height: 844 });
    await assertNoOverflow(page);
    await page.getByRole("slider", { name: "النقطة المعروضة" }).focus();
    await page.getByRole("slider", { name: "النقطة المعروضة" }).press("End");
    await expect(page.locator(".chart-readout")).toContainText("y = 10");
    await page
      .locator(".scientific-chart:not(.scientific-diagram)")
      .screenshot({
        path: `browser-results/science-qa/chart-${mode}-mobile.png`,
      });
    await snapshot(page, `science-${mode}-mobile`);
    expect(errors).toEqual([]);
  });
