import { chooseSubject } from "./helpers";
import { test, expect } from "@playwright/test";
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
  await chooseSubject(page, "physics");
  await page.getByLabel("رسالتك").fill("اشرح الحرارة");
  await page.getByRole("button", { name: "إرسال ↑", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "الحرارة وانتقال الطاقة" }),
  ).toBeVisible({ timeout: 30000 });
  const old = new URL(page.url()).hash.slice(6);
  await chooseSubject(page, "mathematics");
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
