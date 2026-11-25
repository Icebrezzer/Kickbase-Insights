// Run against a local demo server only. No real account or trade is used.
import assert from "node:assert/strict"
import { writeFile } from "node:fs/promises"
const { chromium } = await import(process.env.AUDIT_PLAYWRIGHT_MODULE ?? "playwright")
const BASE = process.env.BASE ?? "http://127.0.0.1:8765"
assert.equal(new URL(BASE).hostname, "127.0.0.1")
const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || undefined })
const results = []
const routes = ["/", "/spieltag", "/markt", "/konkurrenz", "/live", "/liga", "/spieler", "/merkliste", "/vergleich", "/fair-value", "/transfers", "/planer", "/automatik", "/status", "/liga/manager/1002"]
try {
  for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
    const context = await browser.newContext({ viewport, serviceWorkers: "block" })
    await context.route("**/*", route => new URL(route.request().url()).origin === BASE ? route.continue() : route.abort())
    const login = await context.request.post(`${BASE}/api/auth/login`, { data: { email: "demo@demo.de", password: "demo" } })
    assert.equal(login.status(), 200)
    const page = await context.newPage()
    const errors = []
    page.on("pageerror", error => errors.push(String(error)))
    for (const route of routes) {
      await page.goto(BASE + route, { waitUntil: "networkidle" })
      await page.locator("main").waitFor()
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
      results.push({ width: viewport.width, route, overflow, errors: errors.splice(0) })
      assert.equal(overflow, 0, `${viewport.width} ${route}: horizontal overflow`)
      assert.equal(results.at(-1).errors.length, 0, `${route}: JS error`)
    }
    await context.close()
  }
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, serviceWorkers: "block" })
  await context.route("**/*", route => new URL(route.request().url()).origin === BASE ? route.continue() : route.abort())
  await context.request.post(`${BASE}/api/auth/login`, { data: { email: "demo@demo.de", password: "demo" } })
  const page = await context.newPage()
  await page.goto(BASE, { waitUntil: "networkidle" })
  await page.route("**/api/auth/logout", route => route.abort())
  await page.getByRole("button", { name: "Abmelden", exact: true }).first().click()
  await page.getByRole("alert").filter({ hasText: "Abmelden fehlgeschlagen" }).waitFor()
  assert.equal(new URL(page.url()).pathname, "/")
  await page.unroute("**/api/auth/logout")
  await page.getByRole("button", { name: "Abmelden", exact: true }).first().click()
  await page.waitForURL("**/login")
  assert.equal((await context.request.get(`${BASE}/api/auth/me`)).status(), 401)
  results.push({ regression: "logout network failure stays authenticated; successful 204 logs out", passed: true })
  await context.request.post(`${BASE}/api/auth/login`, { data: { email: "demo@demo.de", password: "demo" } })
  await page.goto(BASE, { waitUntil: "networkidle" })
  await context.clearCookies()
  await page.locator('a[href="/automatik"]').first().click()
  await page.waitForURL(url => url.pathname === "/login")
  await page.getByRole("button", { name: "Anmelden", exact: true }).waitFor()
  results.push({ regression: "expired session redirects despite cached user data", passed: true })
  await context.close()
} finally {
  await browser.close()
  if (process.env.REPORT) await writeFile(process.env.REPORT, JSON.stringify(results, null, 2))
}
console.log(JSON.stringify({ screens: results.filter(r => r.route).length, regressions: results.filter(r => r.regression).length, errors: 0 }))
