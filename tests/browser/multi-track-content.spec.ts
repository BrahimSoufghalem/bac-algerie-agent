import { test, expect } from "@playwright/test";
import { signIn, add, publish } from "./markdown-helpers";
test("one Markdown source serves selected tracks without source duplication", async ({
  page,
}) => {
  await signIn(page);
  await add(page, "مرجع متعدد الشعب — UI", "textbook", [
    "علوم تجريبية",
    "رياضيات",
    "تقني رياضي",
  ]);
  await publish(page);
  const docs = (await (await page.request.get("/api/owner/documents")).json())
    .items;
  const doc = docs.find((d: any) => d.title === "مرجع متعدد الشعب — UI");
  expect(doc.tracks).toEqual([
    "experimental_sciences",
    "mathematics",
    "technical_mathematics",
  ]);
  expect(doc.versions).toHaveLength(1);
  const v = await (
    await page.request.get(`/api/owner/versions/${doc.versions[0].id}`)
  ).json();
  expect(v.files).toHaveLength(1);
  expect(v.source_format).toBe("markdown");
});
