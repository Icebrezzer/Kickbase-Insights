import type { ColumnDef } from "@tanstack/react-table"
import { AlertTriangle, ChevronDown, Clock, Flame, Gavel, ShieldAlert, ShoppingCart, Users } from "lucide-react"
import { type ReactNode, useEffect, useMemo, useState } from "react"
import { useAutomationSettings, useBuyPlanner, useManagerMap, useMarket, useRunScout } from "@/api/hooks"
import type { MarketPlayer } from "@/api/types"
import { BidDialog } from "@/components/BidDialog"
import { DataTable, numberColumn } from "@/components/DataTable"
import { Avatar, Delta, Money, PercentDelta, PlayerCell, TrendIcon } from "@/components/kickbase"
import { usePlayerSheet } from "@/components/PlayerSheet"
import { Badge, Card, Chips, PageHeader, QueryState, SearchInput, Segmented, Stat } from "@/components/ui"
import { cn } from "@/lib/cn"
import { compactMoney, countdown, decimal, number, percent } from "@/lib/format"
import { useNow } from "@/lib/hooks"
import { playerName, POSITIONS } from "@/lib/kickbase"

type Filter = "all" | "targets" | "kickbase" | "managers" | "bids"

const DEFAULT_THRESHOLD = 250_000

const POSITION_CHIPS = Object.entries(POSITIONS).map(([value, meta]) => ({ value: Number(value), label: meta.short }))

export default function Market() {
  const query = useMarket()
  return (
    <>
      <PageHeader
        title="Transfermarkt"
        description="Verstärkungen finden, Preise prüfen und Gebote abwägen"
      />
      <QueryState query={query}>{(players) => <MarketView players={players} />}</QueryState>
    </>
  )
}

function MarketView({ players }: { players: MarketPlayer[] }) {
  const managers = useManagerMap()
  const { open } = usePlayerSheet()
  const now = useNow(30_000)
  const [filter, setFilter] = useState<Filter>("all")
  const [positions, setPositions] = useState<number[]>([])
  const [search, setSearch] = useState("")
  const [bidding, setBidding] = useState<MarketPlayer | null>(null)
  const automation = useAutomationSettings()
  const runScout = useRunScout()
  const threshold = automation.data?.scoutThreshold ?? DEFAULT_THRESHOLD
  const isTarget = (p: MarketPlayer) => p.forecast != null && p.forecast >= threshold
  // Opening the market compares the scouting list with the forecasts, the server throttles it
  const autoScout = automation.data?.autoScout
  useEffect(() => {
    if (autoScout) runScout.mutate()
  }, [autoScout])
  // Nobody bids on the players they listed themselves
  const selfId = useMemo(() => [...managers.values()].find((manager) => manager.isSelf)?.id, [managers])
  const canBid = (player: MarketPlayer) => player.sellerId == null || player.sellerId !== selfId

  const counts = useMemo(
    () => ({
      all: players.length,
      targets: players.filter(isTarget).length,
      kickbase: players.filter((p) => p.isFreeAgent).length,
      managers: players.filter((p) => !p.isFreeAgent).length,
      bids: players.filter((p) => p.ownBid != null).length,
    }),
    [players, threshold],
  )

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return players.filter((p) => {
      if (filter === "targets" && !isTarget(p)) return false
      if (filter === "kickbase" && !p.isFreeAgent) return false
      if (filter === "managers" && p.isFreeAgent) return false
      if (filter === "bids" && p.ownBid == null) return false
      if (positions.length && !positions.includes(p.position)) return false
      if (needle && !playerName(p).toLowerCase().includes(needle)) return false
      return true
    })
  }, [players, filter, positions, search, threshold])

  const bidTotal = players.reduce((sum, p) => sum + (p.ownBid ?? 0), 0)
  const nextExpiry = players
    .filter((p) => p.expiresAt && new Date(p.expiresAt).getTime() > now)
    .sort((a, b) => new Date(a.expiresAt!).getTime() - new Date(b.expiresAt!).getTime())[0]

  const columns = useMemo<ColumnDef<MarketPlayer, any>[]>(
    () => [
      {
        id: "player",
        header: "Spieler",
        accessorFn: (p) => playerName(p),
        cell: ({ row }) => <PlayerCell player={row.original} />,
      },
      numberColumn<MarketPlayer>("marketValue", "Marktwert", (p) => p.marketValue, (value, p) => (
        <span className="inline-flex items-center gap-1.5">
          <Money value={value} />
          <TrendIcon value={p.trend} />
        </span>
      )),
      numberColumn<MarketPlayer>("price", "Preis", (p) => p.price, (value, p) => (
        <div>
          <Money value={value} />
          {!p.isFreeAgent && p.price != null && p.marketValue > 0 && (
            <div className="text-xs">
              <PercentDelta value={p.price / p.marketValue - 1} invert />
            </div>
          )}
        </div>
      )),
      numberColumn<MarketPlayer>("forecast", "Prognose", (p) => p.forecast, (value, p) => (
        <span className="inline-flex items-center justify-end gap-1" title={p.projection.length ? `Hochrechnung: ${p.projection.map((v) => compactMoney(v)).join(" → ")}` : undefined}>
          {isTarget(p) && <Flame className="size-3.5 text-warn" aria-label="Transferziel" />}
          <Delta value={value} compact />
        </span>
      )),
      numberColumn<MarketPlayer>("bidLow", "Empfehlung", (p) => p.bidLow, (_, p) => <Recommendation player={p} />, { hideBelow: "md" }),
      numberColumn<MarketPlayer>("ownBid", "Dein Gebot", (p) => p.ownBid, (value, p) => (
        <div className="flex items-center justify-end gap-2">
          {value == null ? (
            <span className="text-muted">–</span>
          ) : (
            <div>
              <Money value={value} className="font-medium" />
              {p.marketValue > 0 && <div className="text-xs text-muted">{percent(value / p.marketValue - 1)}</div>}
            </div>
          )}
          {canBid(p) && <BidButton hasBid={value != null} onClick={() => setBidding(p)} compact />}
        </div>
      )),
      {
        id: "rivals",
        header: "Konkurrenz",
        accessorFn: (p) => p.rivals.filter((r) => r.probability >= 0.35).length,
        cell: ({ row }) => <RivalStack player={row.original} />,
        sortDescFirst: true,
        meta: { hideBelow: "lg" },
      },
      numberColumn<MarketPlayer>("expectedPoints", "Erw. Pkt.", (p) => p.expectedPoints, (value, p) => (
        <span className="tabular-nums" title={[p.playProbability != null ? `spielt in ${Math.round(p.playProbability * 100)} % der Spiele` : null, p.odds ? `Quoten ${p.odds.map((o) => o ?? "–").join(" | ")}` : null].filter(Boolean).join(" · ")}>
          {decimal(value)}
        </span>
      ), { hideBelow: "2xl" }),
      numberColumn<MarketPlayer>("margin", "Bis Spieltag", (p) => p.marginToMatchday, (value, p) => (
        <span title={`${p.updatesToMatchday} Marktwert-Updates bis zur Deadline, abzüglich Aufpreis`}>
          <Delta value={value} compact />
        </span>
      ), { hideBelow: "2xl" }),
      numberColumn<MarketPlayer>("today", "Heute", (p) => p.today, (v) => <Delta value={v} compact />, { hideBelow: "2xl" }),
      numberColumn<MarketPlayer>("yesterday", "Gestern", (p) => p.yesterday, (v) => <Delta value={v} compact />, {
        hideBelow: "3xl",
      }),
      numberColumn<MarketPlayer>("sevenDays", "7 Tage", (p) => p.sevenDays, (v) => <Delta value={v} compact />, {
        hideBelow: "2xl",
      }),
      numberColumn<MarketPlayer>("thirtyDays", "30 Tage", (p) => p.thirtyDays, (v) => <Delta value={v} compact />, {
        hideBelow: "3xl",
      }),
      numberColumn<MarketPlayer>("averagePoints", "Ø Punkte", (p) => p.averagePoints, (v, p) => (
        <span className="tabular-nums" title={`${number(p.totalPoints)} Punkte gesamt`}>
          {number(v)}
        </span>
      ), { hideBelow: "3xl" }),
      {
        id: "seller",
        header: "Verkäufer",
        accessorFn: (p) => p.sellerName ?? "Kickbase",
        cell: ({ row }) => <Seller player={row.original} image={managers.get(row.original.sellerId ?? "")?.image} />,
        meta: { hideBelow: "xl" },
      },
      {
        ...numberColumn<MarketPlayer>(
          "expiresAt",
          "Läuft ab",
          (p) => (p.expiresAt ? new Date(p.expiresAt).getTime() : null),
          (_, p) => <Expiry expiresAt={p.expiresAt} now={now} />,
        ),
        // Soonest expiry first, listings without a deadline at the end
        sortDescFirst: false,
      },
    ],
    [managers, now, selfId, threshold],
  )

  return (
    <div className="space-y-4">
      <Card className="grid grid-cols-2 gap-4 p-4 sm:p-5 lg:grid-cols-4">
        <Stat label="Auf dem Markt" value={counts.all} hint={`${counts.kickbase} von Kickbase`} />
        <Stat label="Von Managern" value={counts.managers} hint="gelistet von Ligamitgliedern" />
        <Stat label="Deine Gebote" value={counts.bids} hint={counts.bids ? `${compactMoney(bidTotal)} gesamt` : "keine offenen Gebote"} />
        <Stat
          label="Läuft als Nächstes ab"
          value={nextExpiry ? countdown(nextExpiry.expiresAt!, now) : "–"}
          hint={nextExpiry ? playerName(nextExpiry) : undefined}
        />
      </Card>

      <BuyPlanner onBid={setBidding} />

      <Card>
        <div className="flex flex-col gap-3 p-4 sm:p-5 lg:flex-row lg:items-center lg:justify-between">
          <Segmented
            value={filter}
            onChange={setFilter}
            options={[
              { value: "all", label: "Alle", count: counts.all },
              { value: "targets", label: "Transferziele", count: counts.targets },
              { value: "kickbase", label: "Kickbase", count: counts.kickbase },
              { value: "managers", label: "Manager", count: counts.managers },
              { value: "bids", label: "Meine Gebote", count: counts.bids },
            ]}
          />
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <Chips options={POSITION_CHIPS} selected={positions} onChange={setPositions} />
            <SearchInput value={search} onChange={setSearch} placeholder="Spieler suchen …" className="sm:w-56" />
          </div>
        </div>
        <DataTable
          data={rows}
          columns={columns}
          initialSorting={[{ id: "expiresAt", desc: false }]}
          getRowId={(p) => p.id}
          onRowClick={(p) => open(p.id)}
          rowClassName={(p) => p.ownBid != null && "bg-accent-soft/40"}
          mobileCard={(p) => <MarketCard player={p} now={now} target={isTarget(p)} onBid={canBid(p) ? () => setBidding(p) : undefined} />}
        />
      </Card>
      <BidDialog player={bidding} onClose={() => setBidding(null)} />
    </div>
  )
}

function BidButton({ hasBid, onClick, compact }: { hasBid: boolean; onClick: () => void; compact?: boolean }) {
  return (
    <button
      type="button"
      onClick={(event) => {
        // The row itself opens the player screen
        event.stopPropagation()
        onClick()
      }}
      className={cn(
        "inline-flex shrink-0 items-center justify-center gap-1.5 rounded-lg border font-medium transition-colors",
        hasBid ? "border-line bg-surface hover:bg-surface-2" : "border-accent/40 bg-accent-soft hover:border-accent",
        compact ? "h-7 px-2 text-xs" : "h-8 px-3 text-sm",
      )}
    >
      <Gavel className="size-3.5" />
      {hasBid ? "Ändern" : "Bieten"}
    </button>
  )
}

function Seller({ player, image }: { player: MarketPlayer; image?: string | null }) {
  if (player.isFreeAgent) return <Badge>Kickbase</Badge>
  return (
    <span className="inline-flex items-center gap-2">
      <Avatar name={player.sellerName ?? "?"} image={image} size={22} />
      <span className="max-w-32 truncate">{player.sellerName}</span>
      {player.sellerInMinus && (
        <span title="Verkäufer steht geschätzt im Minus" className="text-down">
          <ShieldAlert className="size-3.5" />
        </span>
      )}
    </span>
  )
}

function Expiry({ expiresAt, now }: { expiresAt: string | null; now: number }) {
  if (!expiresAt) return <span className="text-muted">–</span>
  const minutes = (new Date(expiresAt).getTime() - now) / 60_000
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 tabular-nums",
        minutes < 60 ? "font-medium text-down" : minutes < 360 ? "text-warn" : "text-muted",
      )}
    >
      <Clock className="size-3.5" />
      {countdown(expiresAt, now)}
    </span>
  )
}

function Rivals({ player, limit = 4 }: { player: MarketPlayer; limit?: number }) {
  if (player.ownClubFull) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-down" title="Dein persönlich eingestelltes Vereinslimit ist erreicht">
        <AlertTriangle className="size-3.5" /> Vereinslimit erreicht
      </span>
    )
  }
  if (player.rivals.length === 0) {
    return <span className="text-xs text-muted">Keine Konkurrenz im Modell ermittelt</span>
  }
  const shown = player.rivals.filter((r) => r.probability >= 0.2).slice(0, limit)
  if (shown.length === 0) return <span className="text-xs font-medium text-up">Kaum Konkurrenz</span>
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      {shown.map((rival) => (
        <span
          key={rival.managerId}
          title={[
            rival.name,
            `${rival.clubPlayers} Spieler vom Verein`,
            `${rival.squadSize} Spieler im Kader`,
            `bietet mit ca. ${Math.round(rival.probability * 100)} %`,
            rival.expectedBid != null ? `vermutlich ca. ${compactMoney(rival.expectedBid)}` : null,
            ...rival.reasons,
            rival.estimatedBalance != null ? `Kontostand ca. ${compactMoney(rival.estimatedBalance)}` : null,
            rival.maxBid != null ? `max. Gebot ca. ${compactMoney(rival.maxBid)}` : null,
          ]
            .filter(Boolean)
            .join(" · ")}
          className={cn(
            "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium",
            rival.probability >= 0.6 ? "bg-down/15" : rival.probability >= 0.35 ? "bg-warn/15" : "bg-surface-2",
          )}
        >
          <Avatar name={rival.name} image={rival.image} size={14} />
          <span className="max-w-20 truncate">{rival.name}</span>
          <span className="tabular-nums">{Math.round(rival.probability * 100)} %</span>
          {rival.inMinus && <ShieldAlert className="size-3 text-down" />}
        </span>
      ))}
      {player.rivals.length > shown.length && <span className="text-[11px] text-muted">+{player.rivals.length - shown.length}</span>}
    </span>
  )
}

/** The likely bidders as overlapping avatars, the details in the tooltip. Keeps table rows short. */
function RivalStack({ player }: { player: MarketPlayer }) {
  if (player.ownClubFull) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-down" title="Du hast schon 3 Spieler dieses Vereins">
        <AlertTriangle className="size-3.5" /> 3/3
      </span>
    )
  }
  const likely = player.rivals.filter((r) => r.probability >= 0.35)
  if (likely.length === 0) return <span className="text-xs font-medium text-up">kaum</span>
  const title = player.rivals
    .filter((r) => r.probability >= 0.2)
    .map((r) => `${r.name}: ${Math.round(r.probability * 100)} %${r.expectedBid ? `, ca. ${compactMoney(r.expectedBid)}` : ""}${r.inMinus ? ", im Minus" : ""}`)
    .join("\n")
  const top = Math.max(...likely.map((r) => r.probability))
  return (
    <span className="inline-flex items-center gap-2" title={title}>
      <span className="flex -space-x-1.5">
        {likely.slice(0, 4).map((r) => (
          <Avatar key={r.managerId} name={r.name} image={r.image} size={22} className="ring-2 ring-surface" />
        ))}
      </span>
      <span className={cn("text-xs tabular-nums", top >= 0.6 ? "text-down" : "text-warn")}>{Math.round(top * 100)} %</span>
    </span>
  )
}

function Recommendation({ player }: { player: MarketPlayer }) {
  if (player.bidLow == null || player.bidHigh == null) return <span className="text-muted">–</span>
  const range =
    player.bidHigh > player.bidLow ? `${compactMoney(player.bidLow)}–${compactMoney(player.bidHigh)}` : compactMoney(player.bidLow)
  return (
    <span className="inline-flex flex-col items-end leading-tight" title="Modellierte Gebotsspanne aus bisherigen Käufen; keine Zuschlagsgarantie">
      <span className="tabular-nums">{range}</span>
      {player.marginLow != null && (
        <span className={cn("text-[11px] tabular-nums", player.marginLow >= 0 ? "text-up" : "text-down")}>
          Marge {player.marginLow >= 0 ? "+" : ""}
          {compactMoney(player.marginLow)}
        </span>
      )}
    </span>
  )
}

function BuyPlanner({ onBid }: { onBid: (player: MarketPlayer) => void }) {
  const query = useBuyPlanner()
  const [open, setOpen] = useState(false)
  const options = query.data ?? []
  const shown = open ? options : options.filter((o) => !o.blocked).slice(0, 3)
  return (
    <Card>
      <button type="button" onClick={() => setOpen(!open)} className="flex w-full items-center justify-between gap-3 px-4 pt-4 pb-2 text-left sm:px-5">
        <span>
          <span className="inline-flex items-center gap-2 text-[15px] font-semibold">
            <ShoppingCart className="size-4" /> Kaufplaner
          </span>
          <span className="mt-0.5 block text-sm text-muted">Jetzt kaufen, bis zum Spieltag halten: Wertgewinn abzüglich Aufpreis und Punkte-Plus für deine beste Elf.</span>
        </span>
        <ChevronDown className={cn("size-5 shrink-0 text-muted transition-transform", open && "rotate-180")} />
      </button>
      <div className="divide-y divide-line px-1 pb-2">
        {query.isPending && <p className="px-4 py-3 text-sm text-muted">Rechne …</p>}
        {!query.isPending && shown.length === 0 && <p className="px-4 py-3 text-sm text-muted">Gerade nichts Lohnendes auf dem Markt.</p>}
        {shown.map((option) => (
          <div key={option.player.id} className={cn("flex items-center justify-between gap-2 px-3 py-2.5 sm:px-4", option.blocked && "opacity-60")}>
            <PlayerCell
              player={option.player}
              className="flex-1"
              sub={
                <span className="truncate">
                  {option.blocked ?? (
                    <>
                      {compactMoney(option.bid)} · Marge{" "}
                      <span className={(option.margin ?? 0) >= 0 ? "text-up" : "text-down"}>
                        {option.margin == null ? "–" : `${option.margin >= 0 ? "+" : ""}${compactMoney(option.margin)}`}
                      </span>
                      {option.pointsGain > 0 && <> · +{decimal(option.pointsGain)} Pkt.</>}
                    </>
                  )}
                </span>
              }
            />
            {!option.blocked && <BidButton hasBid={option.player.ownBid != null} onClick={() => onBid(option.player)} compact />}
          </div>
        ))}
      </div>
    </Card>
  )
}

function MarketCard({ player, now, target, onBid }: { player: MarketPlayer; now: number; target: boolean; onBid?: () => void }) {
  return (
    <div className="space-y-2.5">
      <div className="flex items-start justify-between gap-3">
        <PlayerCell
          player={player}
          className="flex-1"
          sub={
            <span className="flex min-w-0 items-center gap-1">
              <span className="truncate">{player.isFreeAgent ? "Kickbase" : player.sellerName}</span>
              {player.sellerInMinus && <ShieldAlert className="size-3.5 shrink-0 text-down" aria-label="Verkäufer im Minus" />}
            </span>
          }
        />
        <div className="shrink-0 text-right">
          <div className="text-sm font-semibold tabular-nums">{compactMoney(player.price ?? player.marketValue)}</div>
          <Expiry expiresAt={player.expiresAt} now={now} />
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2 rounded-xl bg-surface-2 px-3 py-2 text-xs">
        <Metric label="Heute">
          <Delta value={player.today} compact />
        </Metric>
        <Metric label={target ? "Prognose · Ziel" : "Prognose"}>
          <Delta value={player.forecast} compact />
        </Metric>
        <Metric label={player.marginToMatchday != null ? "bis Spieltag" : "Erw. Pkt."}>
          {player.marginToMatchday != null ? (
            <Delta value={player.marginToMatchday} compact />
          ) : (
            <span className="tabular-nums">{decimal(player.expectedPoints)}</span>
          )}
        </Metric>
      </div>

      <p className="text-xs text-muted">Konkurrenz · Modellschätzung</p>
      <div className="flex items-start gap-1.5 text-xs">
        <Users className="mt-0.5 size-3.5 shrink-0 text-muted" />
        <Rivals player={player} limit={3} />
      </div>

      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0 text-xs">
          {player.ownBid != null ? (
            <span className="rounded-lg bg-accent-soft px-2 py-1">
              Dein Gebot <span className="font-semibold tabular-nums">{compactMoney(player.ownBid)}</span>
            </span>
          ) : player.bidLow != null ? (
            <span>
              <span className="text-muted">Gebotsspanne </span>
              <span className="tabular-nums">
                {compactMoney(player.bidLow)}
                {player.bidHigh != null && player.bidHigh > player.bidLow ? `–${compactMoney(player.bidHigh)}` : ""}
              </span>
              {player.marginLow != null && (
                <span className={cn("ml-1 tabular-nums", player.marginLow >= 0 ? "text-up" : "text-down")}>
                  ({player.marginLow >= 0 ? "+" : ""}
                  {compactMoney(player.marginLow)})
                </span>
              )}
            </span>
          ) : null}
        </div>
        {onBid && <BidButton hasBid={player.ownBid != null} onClick={onBid} />}
      </div>
    </div>
  )
}

function Metric({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] text-muted">{label}</div>
      <div className="break-words font-medium">{children}</div>
    </div>
  )
}
