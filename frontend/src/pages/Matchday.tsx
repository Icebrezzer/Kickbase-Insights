/**
 * The viewer's next matchday: deadline, checks, best eleven by expected points, and the sales that
 * bring a negative budget back to zero. Everything here is asked from Kickbase live.
 */

import { AlertTriangle, CheckCircle2, Info, Lock, Save, ShieldAlert, XCircle } from "lucide-react"
import { useMemo, useState } from "react"
import { useApplyLineup, useCoach, useSell, useTeamMap } from "@/api/hooks"
import type { Check, Coach, SquadPlayer } from "@/api/types"
import { Dialog } from "@/components/Dialog"
import { Money, PlayerCell, PositionBadge, TeamLogo } from "@/components/kickbase"
import { Badge, Button, Card, CardHeader, PageHeader, QueryState, Stat } from "@/components/ui"
import { cn } from "@/lib/cn"
import { compactMoney, countdown, decimal, money, weekdayTime } from "@/lib/format"
import { useNow } from "@/lib/hooks"
import { playerName, POSITIONS } from "@/lib/kickbase"

export default function Matchday() {
  const query = useCoach()
  return (
    <>
      <PageHeader title="Spieltag" description="Deadline, beste Elf und Budget – live aus Kickbase." />
      <QueryState query={query}>{(coach) => <MatchdayView coach={coach} />}</QueryState>
    </>
  )
}

function MatchdayView({ coach }: { coach: Coach }) {
  const now = useNow(15_000)
  const [selling, setSelling] = useState<SquadPlayer | null>(null)
  const byId = useMemo(() => new Map(coach.squad.map((p) => [p.id, p])), [coach.squad])
  const deadline = coach.matchday ? new Date(coach.matchday.deadline).getTime() : null
  const minutesLeft = deadline ? (deadline - now) / 60_000 : null

  return (
    <div className="space-y-4">
      <Card className="grid grid-cols-2 gap-4 p-4 sm:p-5 lg:grid-cols-4">
        <Stat
          label={coach.matchday ? `Deadline Spieltag ${coach.matchday.day}` : "Deadline"}
          value={
            <span className={cn(minutesLeft != null && minutesLeft < 60 && "text-down", minutesLeft != null && minutesLeft < 360 && minutesLeft >= 60 && "text-warn")}>
              {coach.matchday ? countdown(coach.matchday.deadline, now) : "–"}
            </span>
          }
          hint={coach.matchday ? `${weekdayTime(coach.matchday.deadline)} Uhr · Anpfiff ${weekdayTime(coach.matchday.firstKickoff)}` : "Kein Spieltag geplant"}
        />
        <Stat
          label="Budget"
          value={<span className={cn(coach.budget != null && coach.budget < 0 ? "text-down" : "text-up")}>{compactMoney(coach.budget)}</span>}
          hint={coach.budget != null && coach.budget < 0 ? "Muss bis zur Deadline ≥ 0 sein" : "Bereit für den Spieltag"}
        />
        <Stat label="Erwartete Punkte" value={decimal(coach.savedExpected)} hint="deine gespeicherte Elf" />
        <Stat
          label="Beste Elf"
          value={decimal(coach.bestExpected)}
          hint={`${coach.bestFormation} · ${coach.bestExpected - coach.savedExpected >= 0 ? "+" : ""}${decimal(coach.bestExpected - coach.savedExpected)}`}
        />
      </Card>

      <Checks checks={coach.checks} />

      {coach.rescue && <Rescue coach={coach} byId={byId} onSell={setSelling} />}

      <LineupCard coach={coach} byId={byId} />

      <SquadCard coach={coach} onSell={setSelling} />

      <SellDialog player={selling} budget={coach.budget} onClose={() => setSelling(null)} />
    </div>
  )
}

const CHECK_STYLE: Record<Check["level"], { icon: typeof Info; tone: string }> = {
  ok: { icon: CheckCircle2, tone: "text-up" },
  info: { icon: Info, tone: "text-muted" },
  warn: { icon: AlertTriangle, tone: "text-warn" },
  error: { icon: XCircle, tone: "text-down" },
}

function Checks({ checks }: { checks: Check[] }) {
  return (
    <Card className="divide-y divide-line">
      {checks.map((check, index) => {
        const { icon: Icon, tone } = CHECK_STYLE[check.level] ?? CHECK_STYLE.info
        return (
          <div key={index} className="flex items-start gap-3 px-4 py-3 sm:px-5">
            <Icon className={cn("mt-0.5 size-5 shrink-0", tone)} />
            <p className="text-sm">{check.message}</p>
          </div>
        )
      })}
    </Card>
  )
}

function Rescue({ coach, byId, onSell }: { coach: Coach; byId: Map<string, SquadPlayer>; onSell: (p: SquadPlayer) => void }) {
  const rescue = coach.rescue!
  return (
    <Card>
      <CardHeader
        title={
          <span className="inline-flex items-center gap-2">
            <ShieldAlert className="size-4 text-down" /> Budget-Retter
          </span>
        }
        description={
          rescue.enough
            ? `Diese Verkäufe bringen dich auf ca. ${compactMoney(rescue.budgetAfter)} und kosten voraussichtlich ${decimal(rescue.expectedLoss)} Punkte.`
            : "Selbst mit allen Verkäufen wird das Budget nicht positiv."
        }
      />
      <div className="divide-y divide-line px-1 pb-2">
        {rescue.sales.map((id) => {
          const player = byId.get(id)
          if (!player) return null
          return (
            <div key={id} className="flex items-center justify-between gap-3 px-3 py-2.5 sm:px-4">
              <PlayerCell player={player} sub={<span>{player.inLineup ? "Startelf" : "Bank"} · {decimal(player.expected.expected)} erw.</span>} />
              <div className="flex items-center gap-3">
                <span className="text-sm tabular-nums">ca. {compactMoney(player.marketValue)}</span>
                <Button size="sm" onClick={() => onSell(player)}>
                  Verkaufen
                </Button>
              </div>
            </div>
          )
        })}
      </div>
      <p className="px-4 pb-4 text-xs text-muted sm:px-5">
        Kickbase nennt den Sofortverkaufspreis vorher nicht, gerechnet wird mit dem Marktwert. Verkauft wird nur auf deinen Klick.
      </p>
    </Card>
  )
}

function LineupCard({ coach, byId }: { coach: Coach; byId: Map<string, SquadPlayer> }) {
  const apply = useApplyLineup()
  const same = coach.bestLineup.length === coach.savedLineup.length && coach.bestLineup.every((id) => coach.savedLineup.includes(id))
  const rows = [1, 2, 3, 4].map((position) => ({
    position,
    players: coach.bestLineup.map((id) => byId.get(id)).filter((p): p is SquadPlayer => p?.position === position),
  }))
  return (
    <Card>
      <CardHeader
        title={`Beste Elf · ${coach.bestFormation}`}
        description={
          same
            ? "Entspricht deiner gespeicherten Aufstellung."
            : `${coach.savedFormation ?? "Gespeichert"}: ${decimal(coach.savedExpected)} → beste Elf: ${decimal(coach.bestExpected)} erwartete Punkte`
        }
        action={
          coach.lineupOpen ? (
            <Button variant="primary" size="sm" loading={apply.isPending} disabled={same} onClick={() => apply.mutate()}>
              <Save className="size-4" /> In Kickbase speichern
            </Button>
          ) : (
            <Badge>
              <Lock className="size-3" /> gesperrt
            </Badge>
          )
        }
      />
      {apply.error && <p className="px-4 pt-2 text-sm text-down sm:px-5">{apply.error.message}</p>}
      {apply.data && (
        <p className={cn("px-4 pt-2 text-sm sm:px-5", apply.data.confirmed ? "text-up" : "text-warn")}>
          {apply.data.confirmed ? "Gespeichert – Kickbase bestätigt die neue Aufstellung." : "Gesendet, aber Kickbase meldet eine andere Aufstellung zurück. Bitte in der App prüfen."}
        </p>
      )}
      <div className="grid gap-3 p-4 sm:p-5">
        {rows.map(({ position, players }) => (
          <div key={position}>
            <div className="mb-1.5 text-xs font-medium text-muted">{POSITIONS[position].plural}</div>
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
              {players.map((player) => (
                <LineupPlayer key={player.id} player={player} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </Card>
  )
}

function LineupPlayer({ player }: { player: SquadPlayer }) {
  const e = player.expected
  return (
    <div className={cn("flex items-center justify-between gap-3 rounded-xl border border-line px-3 py-2", !player.inLineup && "border-accent/50 bg-accent-soft/30")}>
      <PlayerCell player={player} size={32} sub={<Opponent player={player} />} />
      <div className="text-right">
        <div className={cn("text-sm font-semibold tabular-nums", e.availability === 0 && "text-down")}>{decimal(e.expected)}</div>
        <div className="text-[11px] text-muted">{player.inLineup ? "gespeichert" : "neu"}</div>
      </div>
    </div>
  )
}

function Opponent({ player }: { player: SquadPlayer }) {
  const teams = useTeamMap()
  const e = player.expected
  if (!e.opponentId) return <span className="text-down">{e.reasons.join(", ") || "kein Spiel"}</span>
  const team = teams.get(e.opponentId)
  return (
    <span className="inline-flex min-w-0 items-center gap-1">
      {e.home ? "vs" : "@"}
      <TeamLogo teamId={e.opponentId} size={14} />
      <span className="truncate">{team?.name ?? "?"}</span>
      {e.reasons.length > 0 && <span className="text-warn">· {e.reasons.join(", ")}</span>}
    </span>
  )
}

function SquadCard({ coach, onSell }: { coach: Coach; onSell: (p: SquadPlayer) => void }) {
  return (
    <Card>
      <CardHeader title={`Kader · ${coach.squad.length} Spieler`} description="Erwartete Punkte aus Form (letzte 5 Spiele), Saisonschnitt, Status und Gegnerstärke." />
      <div className="divide-y divide-line px-1 pt-2 pb-2">
        {coach.squad.map((player) => (
          <div key={player.id} className="flex items-center justify-between gap-3 px-3 py-2.5 sm:px-4">
            <div className="flex min-w-0 items-center gap-2">
              <PositionBadge value={player.position} className="hidden sm:inline-flex" />
              <PlayerCell player={player} size={32} sub={<Opponent player={player} />} />
            </div>
            <div className="flex shrink-0 items-center gap-3">
              <div className="hidden text-right text-xs sm:block">
                <div className="text-muted">Form</div>
                <div className="tabular-nums">{decimal(player.expected.form)}</div>
              </div>
              <div className="text-right text-xs">
                <div className="text-muted">Erw.</div>
                <div className={cn("font-semibold tabular-nums", player.inBest ? "text-fg" : "text-muted")}>{decimal(player.expected.expected)}</div>
              </div>
              <div className="hidden text-right text-xs md:block">
                <div className="text-muted">MW</div>
                <Money value={player.marketValue} />
              </div>
              <Button size="sm" variant="ghost" onClick={() => onSell(player)} title="Sofort an Kickbase verkaufen">
                Verkaufen
              </Button>
            </div>
          </div>
        ))}
      </div>
    </Card>
  )
}

function SellDialog({ player, budget, onClose }: { player: SquadPlayer | null; budget: number | null; onClose: () => void }) {
  const sell = useSell()
  const confirm = async () => {
    if (!player) return
    try {
      await sell.mutateAsync(player.id)
      onClose()
    } catch {
      // Shown below
    }
  }
  return (
    <Dialog open={player !== null} onClose={onClose} title="Sofortverkauf" size="small">
      {player && (
        <div className="space-y-4 p-6">
          <h2 className="pr-10 text-lg font-semibold">{playerName(player)} sofort verkaufen?</h2>
          <p className="text-sm text-muted">
            Der Spieler geht sofort an Kickbase. Das lässt sich <strong className="text-fg">nicht rückgängig machen</strong>. Marktwert: {money(player.marketValue)}
            {budget != null && <> · Budget danach ca. {compactMoney(budget + player.marketValue)}</>}.
          </p>
          {player.inLineup && <p className="text-sm text-warn">Er steht in deiner Startelf – die Lücke wird bei aktivierter Automatik neu besetzt.</p>}
          {sell.error && <p className="text-sm text-down">{sell.error.message}</p>}
          <div className="flex justify-end gap-2">
            <Button onClick={onClose}>Abbrechen</Button>
            <Button loading={sell.isPending} onClick={confirm} className="border-down/50 font-semibold text-down">
              Verkaufen
            </Button>
          </div>
        </div>
      )}
    </Dialog>
  )
}
