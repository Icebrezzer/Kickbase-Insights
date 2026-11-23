/**
 * The other managers as bidders: habits, needs, weaknesses, money and the auctions they won against you.
 * Bids at Kickbase are sealed, everything here is read from the transfers of the league.
 */

import { AlertTriangle, Clock, Gavel, ShieldAlert, Target } from "lucide-react"
import type { ReactNode } from "react"
import { Link } from "react-router"
import { usePlayers, useRivals, useTeamMap } from "@/api/hooks"
import type { RivalProfile, Rivals as RivalsData } from "@/api/types"
import { Avatar, TeamLogo } from "@/components/kickbase"
import { Badge, Card, CardHeader, PageHeader, QueryState, Stat } from "@/components/ui"
import { cn } from "@/lib/cn"
import { compactMoney, dateShort, percent, relativeTime } from "@/lib/format"
import { useNow } from "@/lib/hooks"
import { POSITIONS } from "@/lib/kickbase"

export default function Rivals() {
  const query = useRivals()
  return (
    <>
      <PageHeader
        title="Konkurrenz"
        description="Wer bietet wie, wem fehlt was, wer muss verkaufen. Geschätzt aus den Transfers der Liga – Gebote selbst sind bei Kickbase verdeckt."
      />
      <QueryState query={query}>{(data) => <RivalsView data={data} />}</QueryState>
    </>
  )
}

function classLabel(index: number, bounds: number[]) {
  if (index === 0) return `≤ ${compactMoney(bounds[0])}`
  if (index >= bounds.length) return `> ${compactMoney(bounds[bounds.length - 1])}`
  return `${compactMoney(bounds[index - 1])}–${compactMoney(bounds[index])}`
}

function RivalsView({ data }: { data: RivalsData }) {
  return (
    <div className="space-y-4">
      <Card className="grid grid-cols-2 gap-4 p-4 sm:p-5 lg:grid-cols-4">
        {data.leagueOverpayByClass.map((share, index) => (
          <Stat key={index} label={`Ø Aufpreis ${classLabel(index, data.priceClasses)}`} value={percent(share)} hint="Median der Liga" />
        ))}
        <Stat label="Verlorene Auktionen" value={data.lost.length} hint={data.lost[0] ? `zuletzt ${data.lost[0].playerName ?? ""}` : "keine erfasst"} />
      </Card>

      {data.lost.length > 0 && (
        <Card>
          <CardHeader title="Verlorene Auktionen" description="Dein Gebot und was der Gewinner gezahlt hat – daraus lernt die Gebotsempfehlung." />
          <div className="divide-y divide-line px-1 pt-2 pb-2">
            {data.lost.slice(0, 10).map((a) => (
              <div key={`${a.playerId}-${a.date}`} className="flex items-center justify-between gap-3 px-3 py-2 text-sm sm:px-4">
                <span className="min-w-0 truncate">
                  <span className="font-medium">{a.playerName}</span> <span className="text-muted">an {a.winner} · {dateShort(a.date)}</span>
                </span>
                <span className="shrink-0 tabular-nums">
                  {compactMoney(a.ownBid)} → <span className="font-semibold">{compactMoney(a.price)}</span>{" "}
                  <span className="text-down">(+{compactMoney(a.price - a.ownBid)})</span>
                </span>
              </div>
            ))}
          </div>
        </Card>
      )}

      <div className="grid gap-4 xl:grid-cols-2">
        {data.managers.map((manager) => (
          <RivalCard key={manager.id} manager={manager} bounds={data.priceClasses} />
        ))}
      </div>
    </div>
  )
}

function RivalCard({ manager, bounds }: { manager: RivalProfile; bounds: number[] }) {
  const now = useNow(60_000)
  const players = usePlayers()
  const teams = useTeamMap()
  const names = new Map((players.data ?? []).map((p) => [p.id, p.lastName]))
  return (
    <Card className={cn(manager.inMinus && "border-down/50")}>
      <div className="flex flex-wrap items-start justify-between gap-3 p-4 sm:p-5">
        <div className="flex min-w-0 flex-1 basis-56 items-center gap-3">
          <Avatar name={manager.name} image={manager.image} size={40} />
          <div className="min-w-0">
            <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
              <Link to={`/liga/manager/${manager.id}`} className="truncate font-semibold hover:text-accent">
                {manager.name}
              </Link>
              {manager.isSelf && <Badge>Du</Badge>}
              {manager.inMinus && (
                <Badge className="bg-down/15 text-down">
                  <ShieldAlert className="size-3" /> im Minus
                </Badge>
              )}
            </div>
            <p className="text-xs text-muted">
              {manager.squadSize} Spieler · {manager.purchasesRecent} Käufe in 14 Tagen
              {manager.lastActivity && ` · aktiv ${relativeTime(manager.lastActivity, now)}`}
            </p>
          </div>
        </div>
        {manager.maxBid != null && (
          <div className="shrink-0 text-right">
            <div className="text-xs text-muted">max. Gebot</div>
            <div className="font-semibold tabular-nums">{compactMoney(manager.maxBid)}</div>
            <div className={cn("text-xs tabular-nums", (manager.estimatedBalance ?? 0) < 0 ? "text-down" : "text-muted")}>
              Konto ca. {compactMoney(manager.estimatedBalance)}
            </div>
          </div>
        )}
      </div>

      <div className="grid gap-3 border-t border-line p-4 text-sm sm:p-5">
        <Row icon={<Gavel className="size-4" />} label="Aufpreis">
          {manager.overpayMedian == null ? (
            <span className="text-muted">noch keine Käufe von Kickbase</span>
          ) : (
            <span className="flex flex-wrap gap-x-3 gap-y-1">
              <span>Median {percent(manager.overpayMedian)}</span>
              {manager.overpayByClass.map((share, index) =>
                share == null ? null : (
                  <span key={index} className="text-muted">
                    {classLabel(index, bounds)}: <span className="text-fg">{percent(share)}</span>
                  </span>
                ),
              )}
            </span>
          )}
        </Row>
        <Row icon={<Target className="size-4" />} label="Kader">
          <span className="flex flex-wrap gap-2">
            {[1, 2, 3, 4].map((pos) => (
              <span key={pos} className={cn("rounded-md px-1.5 py-0.5 text-xs", manager.needs.includes(pos) ? "bg-warn/15 text-warn" : "bg-surface-2")}>
                {POSITIONS[pos].short} {manager.fitPositions[String(pos)] ?? 0}
                {manager.needs.includes(pos) && " · braucht"}
              </span>
            ))}
          </span>
        </Row>
        {manager.unavailable.length > 0 && (
          <Row icon={<AlertTriangle className="size-4" />} label="Fällt aus">
            <span className="text-warn">{manager.unavailable.map((id) => names.get(id) ?? id).join(", ")}</span>
          </Row>
        )}
        {manager.blockedClubs.length > 0 && (
          <Row icon={<ShieldAlert className="size-4" />} label="3er-Regel">
            <span className="flex flex-wrap items-center gap-1.5">
              {manager.blockedClubs.map((team) => (
                <span key={team} className="inline-flex items-center gap-1 text-xs">
                  <TeamLogo teamId={team} size={16} />
                  {teams.get(team)?.name}
                </span>
              ))}
            </span>
          </Row>
        )}
        {manager.activeHours.length > 0 && (
          <Row icon={<Clock className="size-4" />} label="Kauft meist">
            {manager.activeHours.map((h) => `${h}–${h + 1} Uhr`).join(", ")}
          </Row>
        )}
        {manager.lostTo.length > 0 && (
          <Row icon={<Gavel className="size-4" />} label="Gegen dich">
            {manager.lostTo.length} Auktion(en) gewonnen, Ø{" "}
            {percent(manager.lostTo.reduce((sum, a) => sum + (a.price / a.ownBid - 1), 0) / manager.lostTo.length)} über deinem Gebot
          </Row>
        )}
        {manager.balanceHistory.length > 1 && <BalanceSpark points={manager.balanceHistory} />}
      </div>
    </Card>
  )
}

function Row({ icon, label, children }: { icon: ReactNode; label: string; children: ReactNode }) {
  return (
    <div className="flex items-start gap-3">
      <span className="mt-0.5 text-muted">{icon}</span>
      <span className="w-20 shrink-0 text-muted sm:w-24">{label}</span>
      <span className="min-w-0 break-words">{children}</span>
    </div>
  )
}

/** The estimated balance after every transfer, as a small line */
function BalanceSpark({ points }: { points: { date: string; balance: number }[] }) {
  const width = 300
  const height = 48
  const values = points.map((p) => p.balance)
  const min = Math.min(0, ...values)
  const max = Math.max(0, ...values)
  const span = max - min || 1
  const x = (i: number) => (i / (points.length - 1)) * width
  const y = (v: number) => height - ((v - min) / span) * height
  const path = values.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ")
  return (
    <div>
      <div className="mb-1 text-xs text-muted">Geschätzter Kontostand nach jedem Transfer</div>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-12 w-full" preserveAspectRatio="none" aria-hidden>
        <line x1={0} x2={width} y1={y(0)} y2={y(0)} className="stroke-line" strokeDasharray="4 4" />
        <path d={path} fill="none" className={values[values.length - 1] < 0 ? "stroke-down" : "stroke-accent"} strokeWidth={2} />
      </svg>
    </div>
  )
}
