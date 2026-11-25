import assert from "node:assert/strict"
import test from "node:test"
import { dailyChanges, valueStats } from "../src/lib/valueStats.ts"

test("missing days do not become daily gains or extend streaks", () => {
  const points = [["2026-11-01", 100], ["2026-11-02", 110], ["2026-11-04", 160], ["2026-11-05", 180]]
  assert.deepEqual(dailyChanges(points).map(p => p.change), [10, 20])
  const stats = valueStats(points)
  assert.equal(stats.averageDailyChange, 15)
  assert.equal(stats.change, 80)
  assert.equal(stats.longestRise, 1)
  assert.equal(stats.streak.days, 1)
  assert.equal(valueStats(points.slice(0, 3)).streak.days, 0)
  assert.equal(valueStats([points[0], points[2]]), null)
})

test("contiguous histories retain daily statistics", () => {
  const stats = valueStats([["2026-11-01", 100], ["2026-11-02", 110], ["2026-11-03", 130]])
  assert.equal(stats.averageDailyChange, 15)
  assert.equal(stats.streak.days, 2)
  assert.equal(stats.upDays, 2)
})
