/**
 * What the app may do on its own, push messages on this device, the quality of the market value
 * forecast and a log of everything the automation did.
 */

import { Bell, BellOff, CheckCircle2, Smartphone, XCircle } from "lucide-react"
import { type ReactNode, useEffect, useState } from "react"
import { useAutomationEvents, useAutomationSettings, useForecastQuality, usePushKey, useSaveAutomation } from "@/api/hooks"
import type { AutomationSettings } from "@/api/types"
import { Badge, Button, Card, CardHeader, EmptyState, PageHeader, QueryState, Stat } from "@/components/ui"
import { cn } from "@/lib/cn"
import { dateTime, number, share } from "@/lib/format"
import { currentSubscription, disablePush, enablePush, isIos, isStandalone, pushSupported, testPush } from "@/lib/push"

export default function Automation() {
  const settings = useAutomationSettings()
  return (
    <>
      <PageHeader title="Automatik" description="Was die App für dich erledigt – pro Liga, jederzeit abschaltbar." />
      <div className="space-y-4">
        <PushCard />
        <QueryState query={settings}>{(data) => <SettingsCard initial={data} />}</QueryState>
        <ForecastCard />
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
      </div>
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

const KIND_LABELS: Record<string, string> = {
  lineup: "Aufstellung",
  scout: "Scouting",
  alert: "Deadline",
  sell: "Verkauf",
  push: "Hinweis",
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
