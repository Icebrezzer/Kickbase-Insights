import assert from "node:assert/strict"
import { afterEach, test } from "node:test"
import { api, ApiError } from "../src/api/client.ts"

const originalFetch = globalThis.fetch
afterEach(() => { globalThis.fetch = originalFetch })

test("successful logout accepts the backend's empty 204 response", async () => {
  globalThis.fetch = async () => new Response(null, { status: 204 })
  assert.equal(await api("/auth/logout", { method: "POST" }), undefined)
})

test("JSON responses and API errors retain their data", async () => {
  globalThis.fetch = async () => Response.json({ budget: 0 })
  assert.deepEqual(await api("/coach"), { budget: 0 })
  globalThis.fetch = async () => Response.json({ detail: "Rejected" }, { status: 409 })
  await assert.rejects(api("/test"), error => error instanceof ApiError && error.status === 409)
})

test("network failure is exposed without retrying a mutation", async () => {
  let calls = 0
  globalThis.fetch = async () => { calls++; throw new TypeError("offline") }
  await assert.rejects(api("/test", { method: "POST" }), error => error instanceof ApiError && error.status === 0)
  assert.equal(calls, 1)
})
