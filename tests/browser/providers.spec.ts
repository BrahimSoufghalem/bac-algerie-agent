import { test, expect } from "@playwright/test";
import { navigate, assertNoOverflow, snapshot } from "./helpers";

test("owner: independent provider presets clear secrets and never auto-generate", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByLabel("البريد الإلكتروني").fill("owner@test.invalid");
  await page.getByLabel("كلمة المرور").fill("Test-password-only-1");
  await page.getByRole("button", { name: "دخول", exact: true }).click();
  await navigate(page, "⚙ إعداد النماذج");
  await expect(
    page.getByLabel("نمط الإجابة المنضبطة", { exact: false }),
  ).toBeChecked();
  await page
    .getByRole("button", { name: "ضبط موصى به: إخراج 6000 وإجابة منضبطة" })
    .click();
  await expect(page.getByLabel("حد رموز الإخراج", { exact: true })).toHaveValue(
    "6000",
  );
  await expect(
    page.getByLabel("عشوائية الإجابة (Temperature)", { exact: true }),
  ).toHaveValue("0.1");
  const sent: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" || r.method() === "PUT") sent.push(r.url());
  });
  await page
    .getByRole("combobox", { name: "المزوّد", exact: true })
    .selectOption("google");
  await expect(page.getByLabel("Base URL", { exact: true })).toHaveValue(
    "https://generativelanguage.googleapis.com/v1beta/openai/",
  );
  await expect(page.getByLabel("Model", { exact: true })).toHaveValue(
    "gemini-3.5-flash-lite",
  );
  await page
    .getByLabel("API Key", { exact: true })
    .fill("PRIVATE-BROWSER-FIXTURE");
  await page
    .getByRole("combobox", { name: "المزوّد", exact: true })
    .selectOption("anthropic");
  await expect(page.getByLabel("API Key", { exact: true })).toHaveValue("");
  await expect(
    page.getByText("Anthropic Messages الأصلي", { exact: false }),
  ).toBeVisible();
  await page
    .getByRole("combobox", { name: "الاستخدام", exact: true })
    .selectOption("selector");
  await expect(page.getByLabel("Model", { exact: true })).toHaveValue(
    "gemini-3.5-flash-lite",
  );
  await expect(page.getByLabel("Base URL", { exact: true })).toHaveValue(
    "https://generativelanguage.googleapis.com/v1beta",
  );
  await expect(
    page.getByLabel("تفعيل اختيار المراجع المنسّق للتشغيلات الجديدة"),
  ).not.toBeChecked();
  await expect(
    page.getByText("Google GenerateContent الأصلي", { exact: false }),
  ).toBeVisible();
  await expect(page.getByLabel("حد رموز الإخراج", { exact: true })).toHaveValue(
    "6000",
  );
  await expect(
    page.getByLabel("عشوائية الإجابة (Temperature)", { exact: true }),
  ).toHaveValue("0");
  await expect(
    page.getByLabel("عشوائية الإجابة (Temperature)", { exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByLabel("مسار اختيار المراجع", { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByText("المسار الوحيد: الفهرس الكامل", { exact: false }),
  ).toBeVisible();
  const offeredRouterProviders = page.getByRole("combobox", {
    name: "المزوّد",
    exact: true,
  });
  await expect(
    offeredRouterProviders.locator('option[value="anthropic"]'),
  ).toHaveCount(0);
  await page
    .getByRole("combobox", { name: "المزوّد", exact: true })
    .selectOption("openai");
  await expect(page.getByLabel("Model", { exact: true })).toHaveValue(
    "gpt-4.1-mini",
  );
  await page
    .getByRole("combobox", { name: "المزوّد", exact: true })
    .selectOption("custom");
  await page
    .getByRole("combobox", { name: "بروتوكول المزوّد المخصص", exact: true })
    .selectOption("google");
  await expect(
    page
      .getByRole("combobox", { name: "بروتوكول المزوّد المخصص", exact: true })
      .locator('option[value="evaluation"],option[value="anthropic"]'),
  ).toHaveCount(0);
  await expect(page.getByLabel("Base URL", { exact: true })).toBeEditable();
  expect(sent).toEqual([]);
  await page
    .getByRole("combobox", { name: "المزوّد", exact: true })
    .selectOption("vercel");
  await snapshot(page, "selector-presets-desktop");
  await page.setViewportSize({ width: 390, height: 844 });
  await assertNoOverflow(page);
  await snapshot(page, "selector-presets-mobile");
});
