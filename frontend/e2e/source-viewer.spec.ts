import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, type Page, test } from "@playwright/test";

const EMAIL = process.env.E2E_EMAIL;
const PASSWORD = process.env.E2E_PASSWORD;
// Pang et al. 2023 (open access on arXiv); downloaded once into a git-ignored folder, never committed.
const PAPER_URL = "https://arxiv.org/pdf/2303.11051";
const PAPER = path.join(process.cwd(), "e2e", ".data", "2303.11051.pdf");
const QUESTION =
  "Why do the authors want to 3D print scaffolds with hollow struts?";

const workspaceName = `e2e-${Date.now()}`;

async function fetchPaper() {
  if (existsSync(PAPER)) return;
  const response = await fetch(PAPER_URL);
  expect(response.ok, `download ${PAPER_URL}`).toBe(true);
  mkdirSync(path.dirname(PAPER), { recursive: true });
  writeFileSync(PAPER, Buffer.from(await response.arrayBuffer()));
}

async function deleteWorkspace(page: Page) {
  await page.goto("/workspaces");
  // The list loads after the page; counting rows before that would find none and skip the delete.
  await page.waitForLoadState("networkidle");
  const row = page.getByRole("listitem").filter({ hasText: workspaceName });
  if ((await row.count()) === 0) return;
  await row.getByRole("button", { name: "Delete" }).click();
  await page.getByRole("button", { name: "Delete workspace" }).click();
  await expect(row).toHaveCount(0);
}

test.skip(!EMAIL || !PASSWORD, "E2E_EMAIL and E2E_PASSWORD are not set");

test("upload a paper, ask, and open the highlighted citation", async ({
  page,
}) => {
  await fetchPaper();
  await page.goto("/login");
  await page.getByLabel("Email").fill(EMAIL!);
  await page.getByLabel("Password").fill(PASSWORD!);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/workspaces$/);

  await page.getByRole("button", { name: "New workspace" }).click();
  await page.getByLabel("Name").fill(workspaceName);
  await page.getByRole("button", { name: "Create workspace" }).click();
  await page.getByRole("link", { name: workspaceName }).click();

  await page.locator('input[type="file"]').setInputFiles(PAPER);
  await expect(page.locator('[data-status="ready"]')).toBeVisible({
    timeout: 4 * 60 * 1000,
  });

  await page.getByRole("link", { name: "Ask your papers" }).click();
  await page.getByLabel("Question").fill(QUESTION);
  await page.getByLabel("Question").press("Enter");

  // A citation chip reads "Author Year · p.N"; it appears once the answer is saved.
  const chip = page.getByRole("button", { name: /p\.\d+/ }).first();
  await expect(chip, "the answer should cite the paper").toBeVisible({
    timeout: 3 * 60 * 1000,
  });
  await chip.click();

  const viewer = page.getByRole("dialog");
  await expect(viewer.locator(".textLayer mark").first()).toBeVisible({
    timeout: 60_000,
  });
});

// Runs after a pass or a failure; a cleanup error fails the test so a leftover workspace is noticed.
test.afterEach(async ({ page }) => {
  await deleteWorkspace(page);
});
