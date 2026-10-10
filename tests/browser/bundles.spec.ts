import { test, expect } from "@playwright/test";
import { signIn, add, publish, SOURCE } from "./markdown-helpers";
for (const category of ["exercises", "school_tests", "bac_exams"])
  test(`Markdown ${category} tracks primary source file and its supplied solution`, async ({
    page,
  }) => {
    await signIn(page);
    await add(page, `حزمة ${category} — UI`, category);
    await publish(page);
    const docs = (await (await page.request.get("/api/owner/documents")).json())
      .items;
    const doc = docs.find((d: any) => d.title === `حزمة ${category} — UI`);
    expect(JSON.parse(doc.metadata).content_type).toBe(category);
    const inventory = (
      await (await page.request.get("/api/owner/library/inventory")).json()
    ).items;
    expect(
      inventory.find(
        (r: any) =>
          r.track === "experimental_sciences" && r.subject === "physics",
      ).content[category].added,
    ).toBe(true);
  });
