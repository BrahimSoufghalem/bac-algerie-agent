import { test, expect, Page } from "@playwright/test";
import { navigate, snapshot, assertNoOverflow } from "./helpers";
async function open(page: Page) {
  await page.goto("/");
  await page.getByLabel("البريد الإلكتروني").fill("work-ui@test.invalid");
  await page.getByLabel("كلمة المرور").fill("Test-learning-password-1");
  await page.getByRole("button", { name: "دخول", exact: true }).click();
  await navigate(page, "＋ محادثة جديدة");
}
async function ask(page: Page, question: string) {
  const previous = await page
    .locator(".message.assistant .message-body")
    .count();
  await page.getByLabel("رسالتك").fill(question);
  await page.getByRole("button", { name: "إرسال ↑", exact: true }).click();
  await expect(page.locator(".message.assistant .message-body")).toHaveCount(
    previous + 1,
    { timeout: 30000 },
  );
  await expect(page.locator(".pending-work")).toHaveCount(0, {
    timeout: 30000,
  });
  await expect(
    page.getByRole("heading", { name: "تفسير بعد الرسم" }).last(),
  ).toBeVisible({ timeout: 30000 });
}

test("each answer keeps its drawer above the reply after follow-up, reload and theme/mobile changes", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await open(page);
  await ask(page, "اعرض مثالًا علميًا للمسافة مع رسم بسيط");
  const drawers = page.locator(".message.assistant .work-disclosure");
  await expect(drawers).toHaveCount(1);
  const first = drawers.first();
  const firstRun = await first.getAttribute("data-run");
  await first.getByRole("button").click();
  await expect(first.getByRole("button")).toHaveAttribute(
    "aria-expanded",
    "true",
  );
  const history = await first.locator(".work-timeline").innerText();
  expect(history).toContain("حساب القيم");
  expect(history).toContain("حساب القيم ومراجعتها");
  expect(history).not.toMatch(/calculate|run_python|tool|reasoning|library|get_section/);
  expect(
    await first.evaluate((el) => {
      const article = el.closest(".message")!;
      const body = article.querySelector(".message-body")!;
      return (
        !!(
          el.compareDocumentPosition(body) & Node.DOCUMENT_POSITION_FOLLOWING
        ) && !!article.previousElementSibling?.classList.contains("user")
      );
    }),
  ).toBe(true);
  await first.scrollIntoViewIfNeeded();
  await snapshot(page, "work-drawer-open-desktop");
  await ask(page, "اعرض مثالًا علميًا آخر وبسّط شرحه");
  await expect(drawers).toHaveCount(2);
  await expect(drawers.first()).toHaveAttribute("data-run", firstRun!);
  await expect(drawers.first().getByRole("button")).toHaveAttribute(
    "aria-expanded",
    "true",
  );
  expect(await drawers.first().locator(".work-timeline").innerText()).toBe(
    history,
  );
  await expect(drawers.last().getByRole("button")).toHaveAttribute(
    "aria-expanded",
    "false",
  );
  await page.reload();
  await expect(drawers).toHaveCount(2);
  await drawers.first().getByRole("button").click();
  expect(await drawers.first().locator(".work-timeline").innerText()).toBe(
    history,
  );
  await page
    .getByRole("button", { name: "إعدادات الحساب", exact: true })
    .click();
  await page.getByRole("button", { name: "مظهر داكن", exact: true }).click();
  await page.keyboard.press("Escape");
  await drawers.first().scrollIntoViewIfNeeded();
  await snapshot(page, "work-drawer-dark-desktop");
  for (const width of [390, 360]) {
    await page.setViewportSize({ width, height: 844 });
    await drawers.first().scrollIntoViewIfNeeded();
    await assertNoOverflow(page);
    await snapshot(page, `work-drawer-dark-${width}`);
  }
  await page.emulateMedia({ reducedMotion: "reduce" });
  expect(
    await drawers
      .first()
      .locator(".work-reveal")
      .evaluate((el) => getComputedStyle(el).transitionDuration),
  ).toBe("0s");
  await drawers.first().getByRole("button").focus();
  await page.keyboard.press("Enter");
  await expect(drawers.first().getByRole("button")).toHaveAttribute(
    "aria-expanded",
    "false",
  );
  expect(errors).toEqual([]);
});

test("composed settings and attachment panels: upload/drop, keyboard close, mobile and no accidental send", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await open(page);
  await page
    .getByRole("button", { name: "إعدادات الحساب", exact: true })
    .click();
  await expect(page.locator(".account-summary")).toBeVisible();
  await snapshot(page, "account-refined-desktop");
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("button", { name: "إعدادات الحساب", exact: true }),
  ).toBeFocused();
  const draft = "مسودة لا تُرسل مع إرفاق ملف";
  await page.getByLabel("رسالتك").fill(draft);
  const trigger = page.getByRole("button", {
    name: "إرفاق ملف خاص مؤقتًا · 24 ساعة",
    exact: true,
  });
  await trigger.click();
  await expect(
    page.getByRole("button", { name: "اختر ملفًا أو اسحبه هنا" }),
  ).toBeVisible();
  await snapshot(page, "attachment-refined-desktop");
  let uploads = 0;
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().endsWith("/upload")) uploads++;
  });
  const large = await page.evaluateHandle(() => {
    const d = new DataTransfer();
    d.items.add(
      new File([new Uint8Array(10 * 1024 * 1024 + 1)], "large.txt", {
        type: "text/plain",
      }),
    );
    return d;
  });
  await page
    .locator(".attachment-dropzone")
    .dispatchEvent("drop", { dataTransfer: large });
  await expect(page.getByRole("alert")).toContainText("أكبر من 10 MB");
  expect(uploads).toBe(0);
  const file = await page.evaluateHandle(() => {
    const d = new DataTransfer();
    d.items.add(
      new File(["Private test note"], "my-context.txt", { type: "text/plain" }),
    );
    return d;
  });
  await page
    .locator(".attachment-dropzone")
    .dispatchEvent("drop", { dataTransfer: file });
  await expect(page.locator(".private-file-row")).toContainText(
    "my-context.txt",
  );
  await expect(page.getByLabel("رسالتك")).toHaveValue(draft);
  const chat = new URL(page.url()).hash.slice(6);
  expect(
    (await (await page.request.get(`/api/conversations/${chat}`)).json())
      .messages,
  ).toHaveLength(0);
  for (const width of [390, 360]) {
    await page.setViewportSize({ width, height: 844 });
    await assertNoOverflow(page);
    const panel = await page.locator(".attachment-panel").boundingBox();
    expect(panel!.x).toBeGreaterThanOrEqual(0);
    expect(panel!.x + panel!.width).toBeLessThanOrEqual(width);
    await snapshot(page, `attachment-refined-${width}`);
  }
  await page
    .getByRole("button", { name: "حذف الملف my-context.txt", exact: true })
    .click();
  await expect(page.locator(".private-file-row")).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(trigger).toBeFocused();
  await expect(page.getByLabel("رسالتك")).toHaveValue(draft);
  await page.getByRole("button", { name: "فتح القائمة", exact: true }).click();
  await page
    .getByRole("button", { name: "إعدادات الحساب", exact: true })
    .click();
  await snapshot(page, "account-refined-mobile");
  await assertNoOverflow(page);
  expect(errors).toEqual([]);
});
