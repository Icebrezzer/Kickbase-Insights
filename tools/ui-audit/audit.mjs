// Screenshots of every page on phones, tablet and desktop, plus a report of anything wider than the
// screen or cut off. Runs against the app in demo mode (see .github/workflows/build.yml).
import { mkdir, writeFile } from "node:fs/promises"
import { chromium, devices, webkit } from "playwright"

const BASE = process.env.BASE ?? "http://127.0.0.1:8000"
const OUT = process.env.OUT ?? "out"
const ROUTES = [
  "/", "/spieltag", "/markt", "/konkurrenz", "/live", "/liga", "/spieler", "/merkliste", "/vergleich",
  "/fair-value", "/transfers", "/planer", "/automatik", "/status",
  ...(process.env.EXTRA_ROUTES ? process.env.EXTRA_ROUTES.split(",") : []),
]
const TARGETS = [
  { name: "iphone-se", engine: webkit, device: devices["iPhone SE"], schemes: ["dark"] },
  { name: "iphone-15", engine: webkit, device: devices["iPhone 15 Pro"], schemes: ["dark", "light"] },
  { name: "ipad", engine: webkit, device: devices["iPad (gen 7)"], schemes: ["light"] },
  { name: "desktop", engine: chromium, device: { viewport: { width: 1440, height: 900 } }, schemes: ["dark", "light"] },
  { name: "laptop", engine: chromium, device: { viewport: { width: 1280, height: 720 } }, schemes: ["light"] },
]

/** Runs in the page: what sticks out of the screen, and texts that are cut off */
function inspect() {
  const width = document.documentElement.clientWidth
  const scrollsAway = (el) => {
    for (let node = el.parentElement; node; node = node.parentElement) {
      const style = getComputedStyle(node)
      if (["auto", "scroll", "hidden"].includes(style.overflowX) && node.scrollWidth > node.clientWidth + 1) return true
    }
    return false
  }
  const describe = (el) => {
    const cls = typeof el.className === "string" ? el.className.split(" ").slice(0, 4).join(".") : ""
    return `${el.tagName.toLowerCase()}${cls ? "." + cls : ""} «${(el.innerText || el.textContent || "").trim().slice(0, 50)}»`
  }
  const wide = []
  const cut = []
  for (const el of document.querySelectorAll("main *, nav *, header *")) {
    const rect = el.getBoundingClientRect()
    if (rect.width === 0 || rect.height === 0) continue
    if ((rect.right > width + 1 || rect.left < -1) && !scrollsAway(el)) wide.push(describe(el))
    const style = getComputedStyle(el)
    if (el.children.length === 0 && el.scrollWidth > el.clientWidth + 1 && (style.textOverflow === "ellipsis" || style.overflow === "hidden"))
      cut.push(describe(el))
  }
  return {
    pageOverflow: document.documentElement.scrollWidth - width,
    wide: [...new Set(wide)].slice(0, 15),
    cut: [...new Set(cut)].slice(0, 25),
    cutCount: cut.length,
  }
}

const report = []
await mkdir(OUT, { recursive: true })
for (const target of TARGETS) {
  const browser = await target.engine.launch()
  for (const scheme of target.schemes) {
    const context = await browser.newContext({ ...target.device, colorScheme: scheme, locale: "de-DE", timezoneId: "Europe/Berlin" })
    await context.addInitScript((s) => localStorage.setItem("kbi-theme", s), scheme)
    const login = await context.request.post(`${BASE}/api/auth/login`, { data: { email: "demo@demo.de", password: "demo" } })
    if (!login.ok()) throw new Error(`login failed ${login.status()}`)
    const page = await context.newPage()
    const errors = []
    page.on("pageerror", (e) => errors.push(String(e)))
    for (const route of ROUTES) {
      await page.goto(BASE + route, { waitUntil: "networkidle" }).catch(() => {})
      await page.waitForTimeout(1200)
      const name = `${target.name}-${scheme}${route === "/" ? "-home" : route.replaceAll("/", "-")}`
      await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true })
      report.push({ name, ...(await page.evaluate(inspect)), errors: errors.splice(0) })
    }
    // A few interactions: the "Mehr" sheet on phones, the bid dialog, a player screen
    if (target.name.startsWith("iphone")) {
      await page.goto(BASE + "/", { waitUntil: "networkidle" })
      await page.getByRole("button", { name: "Mehr" }).click().catch(() => {})
      await page.waitForTimeout(600)
      await page.screenshot({ path: `${OUT}/${target.name}-${scheme}-sheet-mehr.png` })
    }
    await page.goto(BASE + "/markt", { waitUntil: "networkidle" })
    const bid = page.getByRole("button", { name: /Bieten/ }).first()
    if (await bid.count()) {
      await bid.click().catch(() => {})
      await page.waitForTimeout(600)
      await page.screenshot({ path: `${OUT}/${target.name}-${scheme}-dialog-gebot.png` })
      report.push({ name: `${target.name}-${scheme}-dialog-gebot`, ...(await page.evaluate(inspect)) })
      await page.keyboard.press("Escape")
    }
    await page.goto(BASE + "/spieler", { waitUntil: "networkidle" })
    await page.locator("main tbody tr, main li, main [role=row]").first().click().catch(() => {})
    await page.waitForTimeout(1500)
    await page.screenshot({ path: `${OUT}/${target.name}-${scheme}-spielerprofil.png`, fullPage: false })
    await context.close()
  }
  await browser.close()
}
await writeFile(`${OUT}/report.json`, JSON.stringify(report, null, 2))
const bad = report.filter((r) => r.pageOverflow > 0 || r.wide?.length || r.errors?.length)
console.log(`${report.length} screens, ${bad.length} with overflow or errors`)
for (const r of bad) {
  console.log(r.name, "overflow", r.pageOverflow, "wide", r.wide?.length ?? 0, r.errors?.length ? r.errors : "")
  for (const w of r.wide ?? []) console.log("   wide:", w)
}
