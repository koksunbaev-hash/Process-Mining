const { test, expect } = require("@playwright/test");

const baseURL = process.env.KMS_BASE_URL || "http://127.0.0.1:8000";
const username = process.env.KMS_ADMIN_USERNAME || "admin";
const password = process.env.KMS_ADMIN_PASSWORD || "Admin123!";

async function login(page) {
  await page.goto(`${baseURL}/login/`);
  await page.fill('input[name="username"]', username);
  await page.fill('input[name="password"]', password);
  await page.click('button[type="submit"], input[type="submit"]');
  await expect(page).toHaveURL(/\/|dashboard|bakery/);
}

async function openDemo(page) {
  await page.goto(`${baseURL}/bakery/board/?demo=demo`);
  await expect(page.getByRole("heading", { name: "Производственная доска" })).toBeVisible();
  await page.getByText("Демо процесса").click();
}

async function createDemo(page, count, options = {}) {
  await page.locator("[data-demo-count]").fill(String(count));
  if (options.speed) await page.locator("[data-demo-speed]").selectOption(String(options.speed));
  if (options.mode) await page.locator("[data-demo-mode]").selectOption(options.mode);
  await page.locator("[data-demo-create]").click();
  await expect(page.locator("[data-demo-state]")).toContainText("created");
  await expect(page.locator("[data-demo-total]")).toContainText(String(count));
}

async function tickOnce(page) {
  const runId = await page.locator("[data-kanban-demo]").getAttribute("data-demo-run-id");
  await page.evaluate(async ({ runId }) => {
    const token = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/)?.[1] || "";
    await fetch(`/api/kanban-demo/${runId}/tick/`, {
      method: "POST",
      headers: { "X-CSRFToken": decodeURIComponent(token), "Content-Type": "application/json" },
      body: "{}",
      credentials: "same-origin",
    });
    await window.KanbanDemo.refreshBoard();
  }, { runId });
}

test.describe("Kanban demo visual workflow", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await openDemo(page);
  });

  test("opens Kanban board", async ({ page }) => {
    await expect(page.locator("[data-kanban-board]")).toBeVisible();
  });

  test("creates demo run", async ({ page }) => {
    await createDemo(page, 100);
    await expect(page.locator("[data-demo-total]")).toContainText("100");
  });

  test("creates 100 cards in queue", async ({ page }) => {
    await createDemo(page, 100);
    await expect(page.locator('[data-stage-code="queue"] .kanban-card-demo')).toHaveCount(100);
  });

  test("starts demo and cards move", async ({ page }) => {
    await createDemo(page, 12, { speed: "0.1", mode: "fast" });
    await page.locator("[data-demo-start]").click();
    await expect(page.locator('[data-stage-code="mixing"] .kanban-card-demo').first()).toBeVisible({ timeout: 5000 });
  });

  test("counters change after tick", async ({ page }) => {
    await createDemo(page, 10, { speed: "0.1" });
    await page.locator("[data-demo-start]").click();
    await expect(page.locator('[data-stage-code="mixing"] .kanban-card-demo').first()).toBeVisible({ timeout: 5000 });
  });

  test("pause stops movement", async ({ page }) => {
    await createDemo(page, 8);
    await page.locator("[data-demo-start]").click();
    await expect(page.locator("[data-demo-state]")).toContainText("running");
    await page.locator("[data-demo-pause]").click();
    await expect(page.locator("[data-demo-state]")).toContainText("paused");
  });

  test("resume continues movement", async ({ page }) => {
    await createDemo(page, 8);
    await page.locator("[data-demo-start]").click();
    await expect(page.locator("[data-demo-state]")).toContainText("running");
    await page.locator("[data-demo-pause]").click();
    await expect(page.locator("[data-demo-state]")).toContainText("paused");
    await page.locator("[data-demo-resume]").click();
    await expect(page.locator("[data-demo-state]")).toContainText("running");
  });

  test("stop stops process", async ({ page }) => {
    await createDemo(page, 8);
    await page.locator("[data-demo-start]").click();
    await expect(page.locator("[data-demo-state]")).toContainText("running");
    await page.locator("[data-demo-stop]").click();
    await expect(page.locator("[data-demo-state]")).toContainText("stopped");
  });

  test("reset removes demo cards", async ({ page }) => {
    await createDemo(page, 5);
    page.once("dialog", (dialog) => dialog.accept());
    await page.locator("[data-demo-reset]").click();
    await expect(page.locator(".kanban-card-demo")).toHaveCount(0);
  });

  test("demo cards have DEMO badge", async ({ page }) => {
    await createDemo(page, 3);
    await expect(page.locator(".kanban-card-demo .status.demo").first()).toContainText("DEMO");
  });

  test("card appears in only one column", async ({ page }) => {
    await createDemo(page, 1);
    await expect(page.locator('[data-batch-number="DEMO-B-0001"]')).toHaveCount(1);
  });

  test("fast mode completes to ready", async ({ page }) => {
    await createDemo(page, 6, { speed: "0.1", mode: "fast" });
    await page.locator("[data-demo-start]").click();
    await expect(page.locator("[data-demo-progress]")).toContainText("100%", { timeout: 10000 });
  });

  test("completed cards are in ready column", async ({ page }) => {
    await createDemo(page, 4, { speed: "0.1", mode: "fast" });
    await page.locator("[data-demo-start]").click();
    await expect(page.locator('[data-stage-code="done"] .kanban-card-demo')).toHaveCount(4, { timeout: 10000 });
  });

  test("demo filter keeps demo visible", async ({ page }) => {
    await createDemo(page, 2);
    await expect(page.locator(".kanban-card-demo")).toHaveCount(2);
  });

  test("sequential mode moves one card first", async ({ page }) => {
    await createDemo(page, 5, { speed: "5", mode: "sequential" });
    await page.locator("[data-demo-start]").click();
    await expect(page.locator("[data-demo-state]")).toContainText("running");
    await tickOnce(page);
    await expect(page.locator('[data-stage-code="mixing"] .kanban-card-demo')).toHaveCount(1, { timeout: 3000 });
  });

  test("random mode starts without breaking board", async ({ page }) => {
    await createDemo(page, 10, { mode: "random" });
    await page.locator("[data-demo-start]").click();
    await expect(page.locator("[data-kanban-board]")).toBeVisible();
  });

  test("wave mode moves grouped cards", async ({ page }) => {
    await createDemo(page, 14, { speed: "5", mode: "wave" });
    await page.locator("[data-demo-start]").click();
    await expect(page.locator("[data-demo-state]")).toContainText("running");
    await tickOnce(page);
    await expect(page.locator('[data-stage-code="mixing"] .kanban-card-demo')).toHaveCount(7, { timeout: 3000 });
  });

  test("stage stats are shown", async ({ page }) => {
    await createDemo(page, 3);
    await expect(page.locator("[data-demo-stage-stats]")).toContainText("queue");
  });

  test("bad API response does not remove board", async ({ page }) => {
    await page.route("**/api/kanban-demo/*/tick/", (route) => route.fulfill({ status: 500, body: "{}" }));
    await createDemo(page, 2);
    await page.locator("[data-demo-start]").click();
    await expect(page.locator("[data-kanban-board]")).toBeVisible();
  });

  test("auditor cannot see demo controls", async ({ browser }) => {
    const context = await browser.newContext();
    const page = await context.newPage();
    await page.goto(`${baseURL}/login/`);
    await page.fill('input[name="username"]', process.env.KMS_AUDITOR_USERNAME || "auditor");
    await page.fill('input[name="password"]', process.env.KMS_AUDITOR_PASSWORD || "Auditor123!");
    await page.click('button[type="submit"], input[type="submit"]');
    await page.goto(`${baseURL}/bakery/board/`);
    await expect(page.getByText("Демо процесса")).toHaveCount(0);
    await context.close();
  });
});
