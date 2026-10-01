import { expect, Page } from "@playwright/test";
import { mkdir, writeFile, readFile } from "node:fs/promises";
import path from "node:path";
const qa = path.resolve("browser-results/previews");
export async function snapshot(page: Page, name: string) {
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
    // Never retain secret input values in offline snapshots.
    clone
      .querySelectorAll('input[type="password"]')
      .forEach((x) => x.removeAttribute("value"));
    return "<!doctype html>" + clone.outerHTML;
  });
  await mkdir(qa, { recursive: true });
  await page.screenshot({
    path: path.join(qa, name + ".png"),
    mask: [page.locator('input[type="password"]')],
  });
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
export async function assertNoOverflow(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
  ).toBe(true);
}

// Account and owner destinations are deliberately out of the primary chat nav.
export async function navigate(page: Page, name: string) {
  await expect(page.locator(".workspace")).toBeVisible();
  const target = page.getByRole("button", { name, exact: true });
  if (await target.isVisible()) {
    await target.click();
    return;
  }
  const mobileToggle = page.getByRole("button", {
    name: "فتح القائمة",
    exact: true,
  });
  if (
    (await mobileToggle.isVisible()) &&
    !(await page
      .locator(".sidebar")
      .evaluate((x) => x.classList.contains("open")))
  )
    await mobileToggle.click();
  if (!(await target.isVisible())) {
    const expand = page.getByRole("button", {
      name: "توسيع الشريط الجانبي",
      exact: true,
    });
    if (await expand.isVisible()) await expand.click();
  }
  if (!(await target.isVisible()))
    await page
      .getByRole("button", { name: "إعدادات الحساب", exact: true })
      .click();
  await target.click();
}
