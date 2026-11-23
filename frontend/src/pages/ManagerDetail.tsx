/**
 * One manager in detail, like BaseXI's league view: values (all, eleven, bench), clubs against the limit,
 * lineup on the pitch for the current or any past matchday, squad with form, transfers, achievements
 * with their prize money, and the season.
 */

import { ChevronLeft, ChevronRight } from "lucide-react"
import { type ReactNode, useMemo, useState } from "react"
import { Link, useParams } from "react-router"
import { useManagerDetail, useTeamMap } from "@/api/hooks"
import type { Achievement, ManagerDetail as Detail, ManagerSquadPlayer, Player } from "@/api/types"
import { SeasonPointsChart, ValueHistoryChart } from "@/components/LazyCharts"
import { Pitch } from "@/components/Pitch"
import { usePlayerSheet } from "@/components/PlayerSheet"
import { Avatar, Delta, Money, PlayerCell, TeamLogo } from "@/components/kickbase"
import { Badge, Card, CardHeader, PageHeader, QueryState, Segmented, Stat } from "@/components/ui"
import { cn } from "@/lib/cn"
import { compactMoney, dateShort, money, number, percent, signedMoney } from "@/lib/format"
import { POSITIONS, pointsGrade } from "@/lib/kickbase"
import { fromKickbase, type Lineup } from "@/lib/lineup"

type Tab = "squad" | "transfers" | "achievements" | "season"
type Split = "total" | "lineup" | "bench"

export default function ManagerDetail() {
  const { id = "" } = useParams()
  const [day, setDay] = useState<number | null>(null)
  const query = useManagerDetail(id, day)
  return (
    <QueryState query={query}>{(detail) => <DetailView key={detail.id} detail={detail} day={day} onDay={setDay} />}</QueryState>
  )
}

function DetailView({ detail, day, onDay }: { detail: Detail; day: number | null; onDay: (day: number | null) => void }) {
  const [tab, setTab] = useState<Tab>("squad")
  const [split, setSplit] = useState<Split>("total")
  const teams = useTeamMap()
  const values = detail[split]
  const shown = split === "total" ? detail.squadSize : split === "lineup" ? detail.lineupIds.length : detail.squadSize - detail.lineupIds.length
  const full = detail.clubs.filter(([, n]) => n >= 3).length

  return (
    <>
      <PageHeader
        title={detail.name}
        description={
          <span className="inline-flex flex-wrap items-center gap-2">
            <Link to="/liga" className="text-accent">
              ← Liga
            </Link>
            <span>
              {number(detail.points)} Punkte · {detail.transfers} Transfers
            </span>
            {detail.placement && <Badge className="bg-warn/15 text-warn">{detail.placement}. Platz</Badge>}
            {detail.isSelf && <Badge>Du</Badge>}
          </span>
        }
        action={
          <div className="flex items-center gap-2">
            <NavButton to={detail.previousId} label="Vorheriger Manager">
              <ChevronLeft className="size-4" />
            </NavButton>
            <NavButton to={detail.nextId} label="Nächster Manager">
              <ChevronRight className="size-4" />
            </NavButton>
          </div>
        }
      />

      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <Avatar name={detail.name} image={detail.image} size={40} />
          <Segmented
            value={split}
            onChange={setSplit}
            options={[
              { value: "total", label: "Gesamt" },
              { value: "lineup", label: "Startelf" },
              { value: "bench", label: "Bank" },
            ]}
          />
        </div>

        <Card className="grid grid-cols-2 gap-4 p-4 sm:p-5 lg:grid-cols-4">
          <Stat label="Teamwert" value={compactMoney(values.teamValue)} hint={`${shown} ${split === "total" ? `/ ${detail.maxSquad} ` : ""}Spieler`} />
          <Stat label="Trend 24 h" value={<Delta value={values.today} compact />} hint="Marktwertänderung heute" />
          <Stat
            label="Transferbilanz"
            value={<span className={detail.transferProfit >= 0 ? "text-up" : "text-down"}>{signedMoney(detail.transferProfit, true)}</span>}
            hint="Gewinn aller abgeschlossenen Handel"
          />
          <Stat label="Ø Aufpreis" value={percent(detail.overpayAverage)} hint="bei Käufen von Kickbase" />
          {detail.maxBid != null && (
            <>
              <Stat
                label="Kontostand (geschätzt)"
                value={<span className={(detail.estimatedBalance ?? 0) < 0 ? "text-down" : ""}>{compactMoney(detail.estimatedBalance)}</span>}
                hint="inkl. Erfolgsprämien"
              />
              <Stat label="Max. Gebot" value={compactMoney(detail.maxBid)} hint="Konto + Kreditrahmen" />
            </>
          )}
          <Stat label="Erfolgsprämien" value={compactMoney(detail.achievementsTotal)} hint="diese Saison" />
        </Card>

        <Card className="p-4 sm:p-5">
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-[15px] font-semibold">Vereine im Kader</h2>
            <span className="text-xs text-muted">
              {detail.clubs.length} Vereine · {full} am Limit (max. 3) ·{" "}
              {[1, 2, 3, 4].map((pos) => `${detail.positions[String(pos)] ?? 0} ${POSITIONS[pos].short}`).join(" · ")}
            </span>
          </div>
          <div className="flex flex-wrap gap-3">
            {detail.clubs.map(([team, count]) => (
              <span key={team} className="relative" title={`${teams.get(team)?.name ?? team}: ${count}/3`}>
                <span
                  className={cn(
                    "grid size-11 place-items-center rounded-full border-2",
                    count >= 3 ? "border-down" : count === 2 ? "border-warn" : "border-line",
                  )}
                >
                  <TeamLogo teamId={team} size={24} />
                </span>
                <span
                  className={cn(
                    "absolute -right-1 -bottom-1 rounded-full px-1 text-[10px] font-semibold tabular-nums",
                    count >= 3 ? "bg-down text-white" : "bg-surface-3",
                  )}
                >
                  {count}/3
                </span>
              </span>
            ))}
          </div>
        </Card>

        <Segmented
          value={tab}
          onChange={setTab}
          options={[
            { value: "squad", label: "Aufstellung & Kader" },
            { value: "transfers", label: "Transfers", count: detail.turnovers.length },
            { value: "achievements", label: "Erfolge" },
            { value: "season", label: "Saisonverlauf" },
          ]}
        />

        {tab === "squad" && <SquadTab detail={detail} day={day} onDay={onDay} />}
        {tab === "transfers" && <TransfersTab detail={detail} />}
        {tab === "achievements" && <AchievementsTab detail={detail} />}
        {tab === "season" && <SeasonTab detail={detail} />}
      </div>
    </>
  )
}

function NavButton({ to, label, children }: { to: string | null; label: string; children: ReactNode }) {
  if (!to) {
    return (
      <span className="grid size-9 place-items-center rounded-xl border border-line text-muted opacity-40" aria-hidden>
        {children}
      </span>
    )
  }
  return (
    <Link to={`/liga/manager/${to}`} aria-label={label} className="grid size-9 place-items-center rounded-xl border border-line hover:bg-surface-2">
      {children}
    </Link>
  )
}

function SquadTab({ detail, day, onDay }: { detail: Detail; day: number | null; onDay: (day: number | null) => void }) {
  const { open } = usePlayerSheet()
  const byId = useMemo(() => {
    // On a past matchday the pitch shows that day's points
    const map = new Map<string, Player>()
    for (const p of detail.squad) map.set(p.id, day ? { ...p, totalPoints: p.dayPoints } : p)
    return map
  }, [detail.squad, day])
  const lineup: Lineup | null = useMemo(
    () => fromKickbase(detail.lineupIds, detail.squad.filter((p) => detail.lineupIds.includes(p.id))),
    [detail.lineupIds, detail.squad],
  )
  const fielded = detail.squad.filter((p) => p.inLineup)
  const bench = detail.squad.filter((p) => !p.inLineup)
  const noop = () => {}

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(300px,420px)_1fr]">
      <Card className="p-3 sm:p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <span className="text-sm font-medium">{day ? `Spieltag ${day}` : "Aktuell eingestellt"}</span>
          <select
            value={day ?? ""}
            onChange={(event) => onDay(event.target.value ? Number(event.target.value) : null)}
            className="h-8 rounded-lg border border-line bg-surface px-2 text-sm"
            aria-label="Spieltag wählen"
          >
            <option value="">Aktuell</option>
            {[...detail.days].reverse().map((d) => (
              <option key={d} value={d}>
                Spieltag {d}
              </option>
            ))}
          </select>
        </div>
        {lineup ? (
          <Pitch
            lineup={lineup}
            players={byId}
            metric={day ? "points" : "average"}
            selected={null}
            activePosition={null}
            onPick={noop}
            onDragStart={noop}
            onDragEnd={noop}
            onDrop={noop}
          />
        ) : (
          <p className="py-10 text-center text-sm text-muted">Keine Aufstellung bekannt.</p>
        )}
        {day && detail.lineupIds.length > 0 && (
          <p className="mt-2 text-xs text-muted">
            Spieler, die inzwischen verkauft sind, fehlen auf dem Feld. Punkte des Spieltags:{" "}
            {number(detail.squad.filter((p) => p.inLineup).reduce((sum, p) => sum + (p.dayPoints ?? 0), 0))}
          </p>
        )}
      </Card>

      <Card>
        <SquadList title={`Startelf (${fielded.length})`} players={fielded} onOpen={open} />
        <SquadList title={`Bank (${bench.length})`} players={bench} onOpen={open} />
      </Card>
    </div>
  )
}

function SquadList({ title, players, onOpen }: { title: string; players: ManagerSquadPlayer[]; onOpen: (id: string) => void }) {
  if (players.length === 0) return null
  return (
    <div>
      <div className="border-b border-line px-4 pt-4 pb-2 text-xs font-medium text-muted sm:px-5">{title}</div>
      <div className="divide-y divide-line px-1">
        {players.map((p) => (
          <button
            key={p.id}
            type="button"
            onClick={() => onOpen(p.id)}
            className="flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left hover:bg-surface-2 sm:px-4"
          >
            <PlayerCell player={p} size={32} sub={<span>Ø {number(p.averagePoints)} · S11 {p.starts ?? "–"}/10</span>} />
            <div className="flex shrink-0 items-center gap-3">
              <Form form={p.form} />
              <div className="text-right text-xs">
                <Money value={p.marketValue} className="block font-medium" />
                <Delta value={p.today} compact />
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}

/** The last five matches as small coloured tiles, hidden on narrow phones */
function Form({ form }: { form: [number, number | null][] }) {
  if (form.length === 0) return null
  return (
    <span className="hidden gap-0.5 min-[420px]:flex">
      {form.map(([day, points]) => {
        const grade = points == null ? null : pointsGrade(points)
        return (
          <span
            key={day}
            title={`Spieltag ${day}: ${points == null ? "nicht gespielt" : `${points} Punkte`}`}
            className="grid h-5 min-w-7 place-items-center rounded px-0.5 text-[10px] font-semibold tabular-nums"
            style={grade ? { background: grade.fill, color: grade.text } : { background: "var(--surface-2)", color: "var(--muted)" }}
          >
            {points ?? "–"}
          </span>
        )
      })}
    </span>
  )
}

function TransfersTab({ detail }: { detail: Detail }) {
  const [view, setView] = useState<"trades" | "transfers">("trades")
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-3 p-4 sm:p-5">
        <Segmented
          value={view}
          onChange={setView}
          options={[
            { value: "trades", label: "Je Handel", count: detail.turnovers.length },
            { value: "transfers", label: "Je Transfer", count: detail.transferList.length },
          ]}
        />
        <span className="text-sm">
          Bilanz <span className={cn("font-semibold tabular-nums", detail.transferProfit >= 0 ? "text-up" : "text-down")}>{signedMoney(detail.transferProfit)}</span>
        </span>
      </div>
      <div className="divide-y divide-line px-1 pb-2">
        {view === "trades"
          ? detail.turnovers.map((t) => (
              <div key={`${t.playerId}-${t.sellDate}`} className="flex items-center justify-between gap-3 px-3 py-2.5 text-sm sm:px-4">
                <div className="min-w-0">
                  <div className="truncate font-medium">{t.playerName}</div>
                  <div className="text-xs text-muted">
                    {t.starter ? "zugelost" : t.buyDate ? `gekauft ${dateShort(t.buyDate)} für ${compactMoney(t.buyPrice)}` : "–"} · verkauft {dateShort(t.sellDate)} für{" "}
                    {compactMoney(t.sellPrice)}
                    {t.soldTo ? ` an ${t.soldTo}` : " an Kickbase"}
                  </div>
                </div>
                <Delta value={t.profit} compact className="shrink-0 font-semibold" />
              </div>
            ))
          : detail.transferList.map((t) => {
              const bought = t.buyerId === detail.id
              return (
                <div key={t.id} className="flex items-center justify-between gap-3 px-3 py-2.5 text-sm sm:px-4">
                  <div className="min-w-0">
                    <div className="truncate font-medium">{t.playerName}</div>
                    <div className="text-xs text-muted">
                      {dateShort(t.date)} · {bought ? `von ${t.seller ?? "Kickbase"}` : `an ${t.buyer ?? "Kickbase"}`}
                    </div>
                  </div>
                  <span className="flex shrink-0 items-center gap-2">
                    <Badge className={bought ? "bg-up/15 text-up" : "bg-down/15 text-down"}>{bought ? "Kauf" : "Verkauf"}</Badge>
                    <span className="tabular-nums">{money(t.price)}</span>
                  </span>
                </div>
              )
            })}
      </div>
    </Card>
  )
}

function AchievementsTab({ detail }: { detail: Detail }) {
  const groups = useMemo(() => {
    const map = new Map<string, Achievement[]>()
    for (const a of detail.achievements) map.set(a.group, [...(map.get(a.group) ?? []), a])
    return [...map.entries()]
  }, [detail.achievements])
  const reached = detail.achievements.filter((a) => (a.count ?? 0) > 0).length
  return (
    <div className="space-y-4">
      <Card className="flex flex-wrap items-end justify-between gap-3 p-4 sm:p-5">
        <Stat label="Erfolge diese Saison" value={`${reached} von ${detail.achievements.length}`} />
        <Stat label="Erfolgsprämien gesamt" value={<span className="text-up">{money(detail.achievementsTotal)}</span>} className="text-right" />
        <p className="w-full text-xs text-muted">
          Aus den Daten der Liga berechnet: Spieltage, Aufstellungen, Spielerpunkte und Transfers. „Einmal je Liga“ zählt auch, wenn es in einer früheren Saison schon kam.
          „Tormaschine“ lässt sich nicht ermitteln, weil Kickbase die Tore je Elf nicht liefert. Die Summe fließt in die geschätzten Kontostände ein.
        </p>
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        {groups.map(([group, items]) => (
          <Card key={group}>
            <CardHeader title={group} action={<span className="font-semibold text-up tabular-nums">{compactMoney(items.reduce((s, a) => s + a.amount, 0))}</span>} />
            <div className="divide-y divide-line px-1 pt-2 pb-2">
              {items.map((a) => (
                <div key={a.key} className={cn("flex items-center justify-between gap-3 px-3 py-2 text-sm sm:px-4", !a.count && "opacity-50")}>
                  <div className="min-w-0">
                    <div className="font-medium">
                      {a.name} <span className="text-xs font-normal text-muted">({compactMoney(a.reward)})</span>
                    </div>
                    <div className="text-xs text-muted">
                      {a.description}
                      {a.kind === "once_per_league" && " · einmal je Liga"}
                    </div>
                  </div>
                  <span className="flex shrink-0 items-center gap-2">
                    {a.count == null ? <Badge>unbekannt</Badge> : a.count > 0 ? <Badge>{a.count}×</Badge> : null}
                    <span className="w-20 text-right tabular-nums">{a.amount ? money(a.amount) : "–"}</span>
                  </span>
                </div>
              ))}
            </div>
          </Card>
        ))}
      </div>
    </div>
  )
}

function SeasonTab({ detail }: { detail: Detail }) {
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title="Punkte je Spieltag" description="Balken: Spieltag · Linie: Gesamtpunkte" />
        <div className="p-3 sm:p-4">
          {detail.season.length ? <SeasonPointsChart rows={detail.season} /> : <p className="py-8 text-center text-sm text-muted">Noch keine Spieltage.</p>}
        </div>
      </Card>
      <Card>
        <CardHeader
          title="Teamwert-Verlauf"
          description="Jeden Abend nach dem Marktwert-Update: der Kader dieses Tages zu den Werten dieses Tages. Verkäufe senken den Teamwert, das Geld landet auf dem Konto."
        />
        <div className="p-3 sm:p-4">
          {detail.teamValues.length > 1 ? (
            <ValueHistoryChart points={detail.teamValues} height={240} />
          ) : (
            <p className="py-8 text-center text-sm text-muted">Noch kein Verlauf.</p>
          )}
        </div>
      </Card>
    </div>
  )
}
