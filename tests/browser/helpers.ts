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
export async function assertNoOverflow(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
  ).toBe(true);
}
