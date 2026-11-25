/**
 * What the app may do on its own, push messages on this device, the quality of the market value
 * forecast and a log of everything the automation did.
 */

import { Bell, BellOff, CheckCircle2, Smartphone, XCircle } from "lucide-react"
import { type ReactNode, useEffect, useState } from "react"
import {
  useAutomationEvents,
  useAutomationSettings,
  useForecastQuality,
  useLearning,
  usePushKey,
  useSaveAutomation,
  useTrader,
  useTraderImport,
  withLeague,
} from "@/api/hooks"
import { useLeagueId } from "@/lib/league"
import type { AutomationSettings, TraderOptions } from "@/api/types"
import { Badge, Button, Card, CardHeader, EmptyState, PageHeader, QueryState, Stat } from "@/components/ui"
import { cn } from "@/lib/cn"
import { compactMoney, dateTime, decimal, number, share } from "@/lib/format"
import { currentSubscription, disablePush, enablePush, isIos, isStandalone, pushSupported, testPush } from "@/lib/push"

export default function Automation() {
  const settings = useAutomationSettings()
  return (
    <>
      <PageHeader title="Automatik" description="Was die App für dich erledigt – pro Liga, jederzeit abschaltbar." />
      <div className="space-y-4">
        <PushCard />
        <QueryState query={settings}>{(data) => <SettingsCard initial={data} />}</QueryState>
        <TraderCard />
        <ForecastCard />
        <LearningCard />
        <EventsCard />
      </div>
    </>
  )
}

function Switch({ checked, onChange, label, hint }: { checked: boolean; onChange: (value: boolean) => void; label: ReactNode; hint?: ReactNode }) {
  return (
    <label className="flex cursor-pointer items-start justify-between gap-4 py-3">
      <span className="min-w-0">
        <span className="block text-sm font-medium">{label}</span>
        {hint && <span className="mt-0.5 block text-xs text-muted">{hint}</span>}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cn("relative mt-0.5 h-6 w-11 shrink-0 rounded-full transition-colors", checked ? "bg-accent" : "bg-surface-3")}
      >
        <span className={cn("absolute top-0.5 left-0.5 size-5 rounded-full bg-white shadow transition-transform", checked && "translate-x-5")} />
      </button>
    </label>
  )
}

function SettingsCard({ initial }: { initial: AutomationSettings }) {
  const save = useSaveAutomation()
  const [form, setForm] = useState(initial)
  const [threshold, setThreshold] = useState(String(initial.scoutThreshold))
  useEffect(() => setForm(initial), [initial])
  const change = (patch: Partial<AutomationSettings>) => {
    const next = { ...form, ...patch }
    setForm(next)
    save.mutate(next)
  }
  const opts = form.traderOptions
  const setOption = (patch: Partial<TraderOptions>) => change({ traderOptions: { ...form.traderOptions, ...patch } })
  const commitThreshold = () => {
    const value = Number(threshold.replace(/\D/g, ""))
    if (Number.isFinite(value) && value !== form.scoutThreshold) change({ scoutThreshold: value })
  }

  return (
    <Card>
      <CardHeader
        title="Automatik in dieser Liga"
        description={
          form.usesServiceAccount
            ? "Läuft dauerhaft über das Server-Konto."
            : form.sessionExpiresAt
              ? `Läuft, solange deine Anmeldung gilt (bis ${dateTime(form.sessionExpiresAt)}). Danach bitte neu anmelden.`
              : "Läuft, solange du angemeldet bist."
        }
        action={save.isPending ? <Badge>speichert …</Badge> : save.isError ? <Badge className="text-down">Fehler</Badge> : null}
      />
      <div className="divide-y divide-line px-4 pb-2 sm:px-5">
        <Switch
          checked={form.autoLineup}
          onChange={(autoLineup) => change({ autoLineup })}
          label="Beste Elf automatisch aufstellen"
          hint="Nach jedem Transfer und bis zur Deadline alle 5–30 Minuten: Form, Gesundheit und Gegner entscheiden, wer spielt."
        />
        <Switch
          checked={form.deadlineAlerts}
          onChange={(deadlineAlerts) => change({ deadlineAlerts })}
          label="Deadline-Warnungen"
          hint="Push 3 Std., 60 und 15 Min. vor dem ersten Anpfiff, wenn das Budget negativ ist oder die Elf Lücken hat."
        />
        <Switch
          checked={form.listingAlerts}
          onChange={(listingAlerts) => change({ listingAlerts })}
          label="Markt-Alarm"
          hint="Push, wenn ein Transferziel oder ein Schnäppchen unter Marktwert gelistet wird, und wenn ein Konkurrent kurz vor der Deadline im Minus steht."
        />
        <Switch
          checked={form.sellAlerts}
          onChange={(sellAlerts) => change({ sellAlerts })}
          label="Tägliche Verkaufsempfehlung"
          hint="Um 20 Uhr: Spieler, die bis zum Spieltag voraussichtlich an Wert verlieren – rechtzeitig vor dem Update um 22 Uhr."
        />
        <Switch
          checked={form.autoScout}
          onChange={(autoScout) => change({ autoScout })}
          label="Transferziele automatisch auf die Scoutingliste"
          hint="Spieler, deren Prognose fürs nächste Marktwert-Update die Schwelle erreicht. Fallen sie darunter, nimmt die App sie wieder runter – deine eigenen Einträge bleiben."
        />
        <div className={cn("grid gap-3 py-3 sm:grid-cols-2", !form.autoScout && "opacity-50")}>
          <label className="text-sm">
            <span className="mb-1 block text-xs font-medium text-muted">Schwelle (€ Plus beim nächsten Update)</span>
            <input
              inputMode="numeric"
              value={Number(threshold.replace(/\D/g, "") || 0).toLocaleString("de-DE")}
              onChange={(event) => setThreshold(event.target.value)}
              onBlur={commitThreshold}
              disabled={!form.autoScout}
              className="h-10 w-full rounded-xl border border-line bg-surface px-3 tabular-nums"
            />
          </label>
          <label className="text-sm">
            <span className="mb-1 block text-xs font-medium text-muted">Höchstens so viele Spieler</span>
            <input
              type="number"
              min={1}
              max={100}
              value={form.scoutLimit}
              onChange={(event) => change({ scoutLimit: Math.max(1, Math.min(100, Number(event.target.value) || 1)) })}
              disabled={!form.autoScout}
              className="h-10 w-full rounded-xl border border-line bg-surface px-3 tabular-nums"
            />
          </label>
        </div>
        <Switch
          checked={form.trader}
          onChange={(trader) => change({ trader })}
          label="Autotrader"
          hint={
            form.traderOnServer === false
              ? "Auf dem Server abgeschaltet (KBI_AUTOMATION__TRADER)."
              : "Bietet für eine bessere Startelf und für Marktwert-Gewinne, verkauft Verletzte, Nicht-Stammspieler und schwache Steigerer – immer mit einem Ersatz pro Position."
          }
        />
        <div className={cn("pb-2", !form.trader && "pointer-events-none opacity-50")}>
          <Switch
            checked={form.traderLive}
            onChange={(traderLive) => {
              if (traderLive && !window.confirm("Ab jetzt bietet und verkauft der Autotrader wirklich bei Kickbase. Verkäufe lassen sich nicht rückgängig machen. Fortfahren?")) return
              change({ traderLive })
            }}
            label="Live handeln"
            hint="Aus: Probelauf – protokolliert und meldet nur, was er tun würde."
          />
          <Switch
            checked={form.traderProfit}
            onChange={(traderProfit) => change({ traderProfit })}
            label="Gewinnhandel zwischen den Spieltagen"
            hint="Kauft Spieler mit steigender Prognose und verkauft sie, sobald die Prognose dreht. Pausiert nach dem Wochen-Stop-Loss."
          />
          <Switch
            checked={opts.shadow}
            onChange={(shadow) => setOption({ shadow })}
            label="Schattentransfers"
            hint="Verfolgt ausgelassene Käufe und echte Verkäufe auf dem Papier weiter: Hätte das Gebot gereicht, was brachte der Spieler, was tat der Marktwert nach dem Verkauf? Daraus lernt er Gebotshöhe, Prognose-Vertrauen und Tausch-Schwelle."
          />
          <details className="py-3">
            <summary className="cursor-pointer text-sm font-medium">Feineinstellungen</summary>
            <div className="mt-3 space-y-4">
              <OptionGroup title="Startelf">
                <OptionField label="Mindest-Plus erwartete Punkte der Elf" value={opts.minGain} min={0} max={100} decimals onCommit={(minGain) => setOption({ minGain })} />
                <OptionField label="Höchster Mehrpreis je zusätzlichem Punkt (€)" hint="Gebot minus Marktwert des verdrängten Spielers, geteilt durch das Punkte-Plus" value={opts.maxCostPerPoint} min={0} max={50_000_000} money onCommit={(maxCostPerPoint) => setOption({ maxCostPerPoint })} />
                <OptionField label="Punkteschnitt mindestens besser (%)" value={opts.minAvgEdge} min={0} max={200} onCommit={(minAvgEdge) => setOption({ minAvgEdge })} />
                <OptionField label="Mindest-Einsatzquote letzte 5 Spiele (%)" value={opts.minPlay} min={0} max={100} onCommit={(minPlay) => setOption({ minPlay })} />
                <OptionField label="Anteil des freien Budgets je Startelf-Gebot (%)" value={opts.lineupShare} min={10} max={100} onCommit={(lineupShare) => setOption({ lineupShare })} />
              </OptionGroup>
              <OptionGroup title="Gewinnhandel">
                <OptionField label="Anteil des freien Budgets je Gewinn-Gebot (%)" value={opts.profitShare} min={10} max={100} onCommit={(profitShare) => setOption({ profitShare })} />
                <OptionField label="Wochen-Stop-Loss (€, 0 = aus)" value={opts.stopLoss} min={0} max={100_000_000} money onCommit={(stopLoss) => setOption({ stopLoss })} />
              </OptionGroup>
              <OptionGroup title="Sicherheit">
                <OptionField label="Budget-Reserve, nie ausgegeben (€)" value={opts.reserve} min={0} max={500_000_000} money onCommit={(reserve) => setOption({ reserve })} />
                <OptionField label="Höchstpreis für einen Ersatzspieler (€)" value={opts.coverMaxPrice} min={0} max={50_000_000} money onCommit={(coverMaxPrice) => setOption({ coverMaxPrice })} />
                <OptionField label="Gebote pro Tag" value={opts.dailyBids} min={0} max={30} onCommit={(dailyBids) => setOption({ dailyBids })} />
                <OptionField label="Verkäufe pro Tag" value={opts.dailySales} min={0} max={30} onCommit={(dailySales) => setOption({ dailySales })} />
                <OptionField label="Verkauf für Platz: Minuten vor Auktionsende" value={opts.sellWindow} min={5} max={180} onCommit={(sellWindow) => setOption({ sellWindow })} />
                <OptionField label="Stammspieler-Sperre: Minuten vor dem 1. Anpfiff" hint="Bis 5 Min. nach dem ersten Anpfiff des Spieltags" value={opts.starterLock} min={0} max={1440} onCommit={(starterLock) => setOption({ starterLock })} />
              </OptionGroup>
            </div>
          </details>
        </div>
      </div>
    </Card>
  )
}

function OptionGroup({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <div className="mb-2 text-xs font-semibold tracking-wide text-muted uppercase">{title}</div>
      <div className="grid gap-3 sm:grid-cols-2">{children}</div>
    </div>
  )
}

/** A number that is saved when the field is left, clamped to the server's bounds. */
function OptionField({
  label,
  hint,
  value,
  min,
  max,
  money,
  decimals,
  onCommit,
}: {
  label: string
  hint?: string
  value: number
  min: number
  max: number
  money?: boolean
  decimals?: boolean
  onCommit: (value: number) => void
}) {
  const [text, setText] = useState(String(value))
  useEffect(() => setText(String(value)), [value])
  const parse = (raw: string) => (money ? Number(raw.replace(/\D/g, "") || 0) : Number(raw.replace(",", ".")))
  const commit = () => {
    const parsed = parse(text)
    const next = Number.isFinite(parsed) ? Math.max(min, Math.min(max, decimals ? parsed : Math.round(parsed))) : value
    setText(String(next))
    if (next !== value) onCommit(next)
  }
  return (
    <label className="text-sm">
      <span className="mb-1 block text-xs font-medium text-muted">{label}</span>
      <input
        inputMode={money ? "numeric" : "decimal"}
        value={money ? parse(text).toLocaleString("de-DE") : text}
        onChange={(event) => setText(event.target.value)}
        onBlur={commit}
        className="h-10 w-full rounded-xl border border-line bg-surface px-3 tabular-nums"
      />
      {hint && <span className="mt-0.5 block text-xs text-muted">{hint}</span>}
    </label>
  )
}

const PURPOSE_LABELS: Record<string, string> = {
  lineup: "Startelf",
  cover: "Ersatz",
  near: "knapp verworfen",
  profit: "Gewinn",
  room: "Platz",
  rescue: "Budget",
  turn: "Prognose",
}
const STATUS_LABELS: Record<string, string> = {
  planned: "Probelauf",
  open: "offen",
  won: "gewonnen",
  lost: "verloren",
  expired: "abgelaufen",
  sold: "verkauft",
  watching: "Auktion läuft",
  holding: "gehalten",
  done: "ausgewertet",
}

/** Debug export for an AI review, and the import of the values it suggests, without a new build */
function TraderTuning() {
  const leagueId = useLeagueId()
  const [days, setDays] = useState(7)
  const importer = useTraderImport()
  const [error, setError] = useState<string | null>(null)

  async function upload(file: File) {
    setError(null)
    try {
      importer.mutate(JSON.parse(await file.text()))
    } catch {
      setError("Die Datei ist kein gültiges JSON.")
    }
  }

  return (
    <details className="rounded-xl border border-line px-3 py-2">
      <summary className="cursor-pointer text-sm font-medium">Debug-Export und Import</summary>
      <div className="space-y-3 py-3 text-sm">
        <p className="text-muted">
          Der Export enthält Einstellungen, gelernte Werte, Gebote, Verkäufe, Schattentransfers und für jede Runde die Begründung je
          Spieler – zum Prüfen mit einer KI. Deren Vorschlag als JSON <code>{'{"options": {…}, "learned": {…}}'}</code> importieren:
          nur die genannten Werte ändern sich, alles wird auf die Grenzen begrenzt. Gelernte Werte gelten für alle Ligen.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={days}
            onChange={(event) => setDays(Number(event.target.value))}
            aria-label="Zeitraum des Exports"
            className="h-9 rounded-lg border border-line bg-surface px-2"
          >
            {[1, 3, 7, 14, 21].map((d) => (
              <option key={d} value={d}>
                letzte {d} {d === 1 ? "Tag" : "Tage"}
              </option>
            ))}
          </select>
          <a
            href={`/api${withLeague(`/automation/trader/export?days=${days}`, leagueId)}`}
            download={`autotrader-${leagueId ?? "liga"}-${new Date().toISOString().slice(0, 10)}.json`}
            className="inline-flex h-9 items-center rounded-lg border border-line px-3 font-medium hover:bg-surface-2"
          >
            Exportieren
          </a>
          <label className="inline-flex h-9 cursor-pointer items-center rounded-lg border border-line px-3 font-medium hover:bg-surface-2">
            Importieren…
            <input
              type="file"
              accept="application/json,.json"
              className="sr-only"
              onChange={(event) => {
                const file = event.target.files?.[0]
                event.target.value = ""
                if (file) void upload(file)
              }}
            />
          </label>
        </div>
        {(error || importer.error) && <p className="text-down">{error ?? importer.error?.message}</p>}
        {importer.data && (
          <p className="text-up">
            Übernommen.
            {importer.data.ignored.length > 0 && <span className="text-muted"> Unbekannt und ignoriert: {importer.data.ignored.join(", ")}</span>}
          </p>
        )}
      </div>
    </details>
  )
}

function TraderCard() {
  const query = useTrader()
  return (
    <Card>
      <CardHeader
        title="Autotrader"
        description="Wochenbilanz, letzte Gebote und Verkäufe. Gelernt wird aus allen Ligen gemeinsam."
        action={query.data?.paused ? <Badge className="text-down">Gewinnhandel pausiert</Badge> : null}
      />
      <QueryState query={query}>
        {(tr) => {
          const week = tr.weeks[0]
          const auctions = tr.learned.won + tr.learned.lost
          return (
            <div className="space-y-4 p-4 sm:p-5">
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                <Stat label="Gewinn diese Woche" value={week ? compactMoney(week.profit) : "–"} hint={week ? `${week.sales} Verkäufe, ${compactMoney(week.received)} erlöst` : "noch kein Handel"} />
                <Stat label="Gebote diese Woche" value={week ? `${week.won} / ${week.bids}` : "–"} hint={week ? `gewonnen · ${week.planned} im Probelauf` : undefined} />
                <Stat label="Zuschlagsquote" value={auctions ? share(tr.learned.won / auctions) : "–"} hint={`aus ${number(auctions)} Auktionen`} />
                <Stat label="Mindest-Gewinn" value={compactMoney(tr.learned.minMargin)} hint={`Gebotshöhe je Preisklasse ${tr.learned.extra.map((x) => decimal(x * 100)).join(" / ")} %`} />
                <Stat
                  label="Schattentransfers"
                  value={tr.shadowSummary.done ? compactMoney(tr.shadowSummary.profit) : "–"}
                  hint={`${tr.shadowSummary.done} ausgewertet, ${tr.shadowSummary.open} laufen · Trefferquote ${share(tr.shadowSummary.hitRate)}`}
                />
                <Stat
                  label="Prognose-Vertrauen"
                  value={share(tr.learned.gainScale)}
                  hint={tr.learned.gainSamples >= 10 ? `aus ${tr.learned.gainSamples} Verläufen` : `lernt ab 10 Verläufen (${tr.learned.gainSamples})`}
                />
                <Stat
                  label="Tausch-Schwelle"
                  value={compactMoney(tr.learned.swapEdge)}
                  hint={`mehr Prognose pro Tag als der Verkaufte · nach Verkauf gestiegen: ${share(tr.shadowSummary.soldThenRose)}`}
                />
                <Stat label="Auktionen auf dem Papier" value={`${tr.learned.shadowWon} / ${tr.learned.shadowWon + tr.learned.shadowLost}`} hint="hätte das Gebot gereicht" />
              </div>
              <TraderTuning />

              {tr.weeks.length > 0 && (
                <div className="overflow-x-auto">
                  {/* Phones get the five columns that matter, the rest from sm on */}
                  <table className="w-full text-sm tabular-nums">
                    <thead className="text-left text-xs text-muted">
                      <tr>
                        <th className="py-1 pr-3 font-medium">Woche</th>
                        <th className="hidden py-1 pr-3 font-medium sm:table-cell">Gebote</th>
                        <th className="py-1 pr-3 font-medium">Gekauft</th>
                        <th className="py-1 pr-3 font-medium">Verkauft</th>
                        <th className="hidden py-1 pr-3 font-medium sm:table-cell">Ausgaben</th>
                        <th className="hidden py-1 pr-3 font-medium sm:table-cell">Erlöse</th>
                        <th className="py-1 pr-3 font-medium">Gewinn</th>
                        <th className="hidden py-1 pr-3 font-medium sm:table-cell">+Punkte</th>
                        <th className="py-1 font-medium">Schatten</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line">
                      {tr.weeks.map((w) => (
                        <tr key={w.week}>
                          <td className="py-1.5 pr-3">{w.week.replace(/^\d{4}-/, "")}</td>
                          <td className="hidden py-1.5 pr-3 sm:table-cell">{w.bids}</td>
                          <td className="py-1.5 pr-3">{w.won}</td>
                          <td className="py-1.5 pr-3">{w.sales}</td>
                          <td className="hidden py-1.5 pr-3 sm:table-cell">{compactMoney(w.spent)}</td>
                          <td className="hidden py-1.5 pr-3 sm:table-cell">{compactMoney(w.received)}</td>
                          <td className={cn("py-1.5 pr-3", w.profit > 0 ? "text-up" : w.profit < 0 ? "text-down" : "")}>{compactMoney(w.profit)}</td>
                          <td className="hidden py-1.5 pr-3 sm:table-cell">{decimal(w.pointsGain)}</td>
                          <td className="py-1.5">{w.shadowTrades ? compactMoney(w.shadowProfit) : "–"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {tr.trades.length === 0 ? (
                <EmptyState title="Noch kein Handel" />
              ) : (
                <div className="divide-y divide-line">
                  {tr.trades.map((trade) => (
                    <div key={trade.id} className="flex items-start justify-between gap-3 py-2">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
                          <Badge>{trade.kind === "bid" ? "Gebot" : "Verkauf"}</Badge>
                          <Badge>{PURPOSE_LABELS[trade.purpose] ?? trade.purpose}</Badge>
                          {dateTime(trade.at)}
                        </div>
                        <p className="mt-0.5 text-sm break-words">
                          {trade.name ?? trade.playerId} · {compactMoney(trade.price)}
                          {trade.reason && <span className="text-muted"> – {trade.reason}</span>}
                        </p>
                      </div>
                      <div className="shrink-0 text-right text-sm tabular-nums">
                        <div className="text-xs text-muted">{STATUS_LABELS[trade.status] ?? trade.status}</div>
                        {trade.profit != null && <div className={trade.profit >= 0 ? "text-up" : "text-down"}>{compactMoney(trade.profit)}</div>}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {tr.shadows.length > 0 && (
                <div>
                  <div className="mb-1.5 text-xs font-medium text-muted">Schattentransfers – nur auf dem Papier</div>
                  <div className="divide-y divide-line">
                    {tr.shadows.map((s) => (
                      <div key={s.id} className="flex items-start justify-between gap-3 py-2 text-sm">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
                            <Badge>{s.kind === "buy" ? "Kauf" : "nach Verkauf"}</Badge>
                            <Badge>{PURPOSE_LABELS[s.purpose] ?? s.purpose}</Badge>
                            {dateTime(s.at)}
                          </div>
                          <p className="mt-0.5 break-words">
                            {s.name ?? s.playerId}
                            {s.kind === "buy" && ` · Gebot ${compactMoney(s.bid)}`}
                            {s.winnerPrice != null && <span className="text-muted"> · Zuschlag bei {compactMoney(s.winnerPrice)}</span>}
                          </p>
                        </div>
                        <div className="shrink-0 text-right tabular-nums">
                          <div className="text-xs text-muted">{STATUS_LABELS[s.status] ?? s.status}</div>
                          {s.result != null && <div className={s.result >= 0 ? "text-up" : "text-down"}>{compactMoney(s.result)}</div>}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )
        }}
      </QueryState>
    </Card>
  )
}

function PushCard() {
  const key = usePushKey()
  const [subscribed, setSubscribed] = useState<boolean | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)
  const supported = pushSupported()

  useEffect(() => {
    currentSubscription().then((sub) => setSubscribed(sub !== null)).catch(() => setSubscribed(false))
  }, [])

  const run = async (action: () => Promise<unknown>, success: string) => {
    setBusy(true)
    setMessage(null)
    try {
      await action()
      setMessage({ ok: true, text: success })
      setSubscribed((await currentSubscription()) !== null)
      key.refetch()
    } catch (error) {
      setMessage({ ok: false, text: error instanceof Error ? error.message : String(error) })
    } finally {
      setBusy(false)
    }
  }

  let body: ReactNode
  if (key.data && !key.data.publicKey) {
    body = <p className="text-sm text-muted">Push ist auf dem Server nicht eingerichtet. Dafür muss KBI_PUSH__SUBJECT gesetzt sein.</p>
  } else if (!supported) {
    body =
      isIos() && !isStandalone() ? (
        <ol className="list-decimal space-y-1 pl-5 text-sm text-muted">
          <li>In Safari auf „Teilen“ tippen und „Zum Home-Bildschirm“ wählen.</li>
          <li>Die App vom Home-Bildschirm öffnen und hierher zurückkommen.</li>
          <li>„Auf diesem Gerät aktivieren“ tippen und Mitteilungen erlauben.</li>
        </ol>
      ) : (
        <p className="text-sm text-muted">Dieser Browser unterstützt keine Push-Mitteilungen.</p>
      )
  } else {
    body = (
      <div className="flex flex-wrap items-center gap-2">
        {subscribed ? (
          <>
            <Button loading={busy} onClick={() => run(testPush, "Testnachricht gesendet.")}>
              <Bell className="size-4" /> Testnachricht
            </Button>
            <Button variant="ghost" loading={busy} onClick={() => run(disablePush, "Auf diesem Gerät abgeschaltet.")}>
              <BellOff className="size-4" /> Abschalten
            </Button>
          </>
        ) : (
          <Button variant="primary" loading={busy} disabled={!key.data?.publicKey} onClick={() => run(() => enablePush(key.data!.publicKey!), "Push ist aktiv.")}>
            <Smartphone className="size-4" /> Auf diesem Gerät aktivieren
          </Button>
        )}
      </div>
    )
  }

  return (
    <Card>
      <CardHeader
        title="Push-Mitteilungen"
        description={key.data?.subscribed ? `${key.data.subscribed} Gerät(e) angemeldet` : "Warnungen vor der Deadline und neue Transferziele aufs Handy."}
      />
      <div className="space-y-3 p-4 sm:p-5">
        {body}
        {message && (
          <p className={cn("inline-flex items-center gap-1.5 text-sm", message.ok ? "text-up" : "text-down")}>
            {message.ok ? <CheckCircle2 className="size-4" /> : <XCircle className="size-4" />} {message.text}
          </p>
        )}
      </div>
    </Card>
  )
}

function ForecastCard() {
  const query = useForecastQuality()
  return (
    <Card>
      <CardHeader
        title="Marktwert-Prognose"
        description="Lernt jeden Abend aus den Marktwerten aller Spieler. Jede Prognose wird mit dem echten Update verglichen."
      />
      <QueryState query={query}>
        {(q) => (
          <div className="grid grid-cols-2 gap-4 p-4 sm:p-5 lg:grid-cols-4">
            <Stat
              label="Modell"
              value={q.learned ? "gelernt" : "Startwerte"}
              hint={q.learned ? `${number(q.trainingRows)} Tage × Spieler` : "Lernt, sobald genug Verlauf gespeichert ist"}
            />
            <Stat
              label="Fehler vs. „wie gestern“"
              value={q.error != null && q.naiveError != null ? `${share(1 - q.error / q.naiveError)} besser` : "–"}
              hint="auf den Trainingsdaten"
            />
            <Stat label="Richtung getroffen" value={share(q.directionHits)} hint={`${number(q.checked)} Prognosen geprüft`} />
            <Stat label="Treffer bei Transferzielen" value={share(q.flagPrecision)} hint="Prognose ≥ Schwelle und wirklich gestiegen" />
          </div>
        )}
      </QueryState>
    </Card>
  )
}

function LearningCard() {
  const query = useLearning()
  return (
    <Card>
      <CardHeader title="Lernstand" description="Was die App aus den Daten deiner Liga gelernt hat. Alles passt sich laufend selbst an." />
      <QueryState query={query}>
        {(l) => {
          const e = l.expectation
          const mode = l.achievementMode.mode ?? "matchday"
          const compared = l.achievements.filter((a) => a.kickbase != null)
          return (
            <div className="space-y-4 p-4 sm:p-5">
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-3">
                <Stat
                  label="Erwartete Punkte"
                  value={e.rows ? "gelernt" : "Startwerte"}
                  hint={
                    e.error != null && e.defaultError != null
                      ? `Fehler ${decimal(e.error)} statt ${decimal(e.defaultError)} Pkt. · ${number((e.historyRows ?? 0) + (e.loggedRows ?? 0))} Spiele`
                      : `${number(e.historyRows ?? 0)} vergangene Spiele, ${number(l.expectationChecked)} geprüfte Vorhersagen`
                  }
                />
                <Stat
                  label="Gewichte"
                  value={`${decimal((e.form ?? 0.6) * 100)} / ${decimal((e.average ?? 0.4) * 100)}`}
                  hint={`Form / Schnitt · Quoten ${decimal(e.win ?? 0.4)} · Tabelle ${decimal(e.table ?? 0.15)}`}
                />
                <Stat
                  label="Bieter-Modell"
                  value={l.bidder.weights?.length ? "gelernt" : `${l.auctionsResolved} / 50`}
                  hint={l.bidder.weights?.length ? `aus ${l.bidder.auctions} Auktionen` : `Auktionen ausgewertet, ${l.auctionsLogged} erfasst`}
                />
                <Stat
                  label="Budget-Korrektur"
                  value={l.balanceCorrection?.members ? compactMoney(l.balanceCorrection.amount) : "–"}
                  hint={l.balanceCorrection?.members ? `aus ${l.balanceCorrection.members} echten Kontoständen` : "braucht einen echten Kontostand"}
                />
                <Stat
                  label="Sofortverkauf"
                  value={l.sellRatio.ratio ? share(l.sellRatio.ratio) : "–"}
                  hint={l.sellRatio.ratio ? `vom Marktwert, aus ${l.sellRatio.sales} Verkäufen` : "lernt beim ersten Verkauf"}
                />
                <Stat
                  label="Spieler-Erfolge"
                  value={mode === "player" ? "je Spieler" : "je Spieltag"}
                  hint={`Stimmen ${l.achievementMode.votesMatchday ?? 0} : ${l.achievementMode.votesPlayer ?? 0} (Spieltag : Spieler)`}
                />
              </div>
              {compared.length > 0 && (
                <div>
                  <div className="mb-1.5 text-xs font-medium text-muted">
                    Deine Erfolge: Kickbase-Zähler (alle Saisons) und App (diese Saison)
                    {l.achievementsCheckedAt && ` · Stand ${dateTime(l.achievementsCheckedAt)}`}
                  </div>
                  <div className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
                    {compared.map((a) => (
                      <div key={a.key} className="flex justify-between gap-3">
                        <span className="truncate">{a.name}</span>
                        <span className={cn("tabular-nums", a.app != null && a.kickbase != null && a.app > a.kickbase && "text-warn")}>
                          {a.kickbase} / {a.app ?? "–"}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )
        }}
      </QueryState>
    </Card>
  )
}

const KIND_LABELS: Record<string, string> = {
  lineup: "Aufstellung",
  scout: "Scouting",
  alert: "Deadline",
  sell: "Verkauf",
  push: "Hinweis",
  trader: "Autotrader",
}

function EventsCard() {
  const query = useAutomationEvents()
  return (
    <Card>
      <CardHeader title="Protokoll" description="Alles, was die Automatik getan oder versucht hat." />
      <QueryState query={query}>
        {(events) =>
          events.length === 0 ? (
            <EmptyState title="Noch nichts passiert" />
          ) : (
            <div className="divide-y divide-line px-1 pt-2 pb-2">
              {events.map((event) => (
                <div key={event.id} className="flex items-start gap-3 px-3 py-2.5 sm:px-4">
                  {event.ok ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-up" /> : <XCircle className="mt-0.5 size-4 shrink-0 text-down" />}
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
                      <Badge>{KIND_LABELS[event.kind] ?? event.kind}</Badge>
                      {dateTime(event.at)}
                    </div>
                    <p className="mt-0.5 text-sm break-words">{event.message}</p>
                  </div>
                </div>
              ))}
            </div>
          )
        }
      </QueryState>
    </Card>
  )
}
