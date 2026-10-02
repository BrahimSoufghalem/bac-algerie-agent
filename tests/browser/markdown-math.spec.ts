import { test, expect } from "@playwright/test";
import { normalizeMathDelimiters } from "../../frontend/src/markdownMath";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import Markdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";

test("original TeX delimiters render without changing code or source text", async ({ page }) => {
  const raw = String.raw`كمية المادة \(n=\frac{m}{M}\) بوحدة mol.
\[X(t_{1/2})=\frac{X_{max}}{2}\]
\`not a code delimiter`;
  const adapted = normalizeMathDelimiters(raw);
  expect(adapted).toContain(String.raw`$n=\frac{m}{M}$`);
  const html = renderToStaticMarkup(
    React.createElement(
      Markdown,
      { skipHtml: true, remarkPlugins: [remarkMath],
        rehypePlugins: [[rehypeKatex, { trust: false, maxExpand: 1000 }]] },
      adapted,
    ),
  );
  expect(html.match(/class="katex"/g)).toHaveLength(2);
  expect(html).not.toContain("katex-error");
  for (const code of [
    "`\\(n=m/M\\)`", "``\\(n=m/M\\) `literal` ``",
    "```latex\n\\(n=m/M\\)\n```",
    "~~~latex\n\\[n=m/M\\]\n~~~",
    "```unclosed\n\\(n=m/M\\)",
    "\\\\(literal)", "\\(unclosed", "$n=m/M$",
  ]) expect(normalizeMathDelimiters(code)).toBe(code);
  expect(raw).toContain(String.raw`\(n=\frac{m}{M}\)`);
  await page.goto("/");
  await page.evaluate((rendered) => {
    const box = document.createElement("div");
    box.id = "rtl-math-check";
    box.dir = "rtl";
    box.innerHTML = rendered;
    document.body.appendChild(box);
  }, html);
  const first = page.locator("#rtl-math-check .katex").first();
  await expect(first).toHaveCSS("direction", "ltr");
  await expect(first).toHaveCSS("unicode-bidi", "isolate");
  const n = await first.locator(".katex-html .mord").first().boundingBox();
  const fraction = await first.locator(".katex-html .mfrac").first().boundingBox();
  expect(n!.x).toBeLessThan(fraction!.x); // n = m/M, not m/M = n under RTL
});