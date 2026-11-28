import { useShadowReport } from "@/api/hooks"
import { Card, CardHeader, QueryState, Stat } from "@/components/ui"
import { compactMoney } from "@/lib/format"

const names: Record<string, string> = {
  missed: "Entgangener Gewinn", avoided: "Vermiedener Verlust", purchased: "Tatsächlich gekauft",
  lost: "Unterlegen", won: "Gewonnen", no_buyer: "Kein Käufer", unknown: "Unbekannt",
  hypothetical: "Einzelhypothese", unavailable: "Ohne Modellgebot",
  minimum: "Mindestgebot", defensive: "Defensiv", standard: "Standard", aggressive: "Aggressiv", ev: "EV-optimal",
  hold_1: "1 Update", hold_2: "2 Updates", hold_3: "3 Updates", forecast: "Prognose-Ausstieg",
  trailing: "Trailing-Stop", deadline: "Deadline-Verkauf",
  feasible: "einzeln finanzierbar", infeasible: "einzeln nicht finanzierbar",
}
const label = (key: string) => names[key] ?? key
const money = (value: number | null) => value === null ? "–" : compactMoney(value)

export function ShadowIntelligence() {
  const query = useShadowReport()
  return <Card>
    <CardHeader title="Shadow Intelligence" description="Wie hätten sich andere Gebote und Verkaufszeitpunkte ausgewirkt?" />
    <QueryState query={query}>{d => <div className="space-y-4 p-4 text-sm">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Beobachtete Auktionen" value={d.observed} />
        <Stat label="Entgangene Gewinne · finanzierbare Fälle" value={d.feasible.missed ?? 0} />
        <Stat label="Vermiedene Verluste · finanzierbare Fälle" value={d.feasible.avoided ?? 0} />
        <Stat label="Realisierter Gewinn / Verlust" value={money(d.realized.sum)} hint={d.realized.count + " bestätigte Verkäufe mit Ergebnis"} />
      </div>
      <p className="text-muted">Die letzten {d.days} Tage, bis zu {d.limit} Auktionen. Hypothetische Ergebnisse gelten einzeln.
        Andere Manager hätten anders reagieren können. Referenz ist das Standardgebot mit Verkauf nach zwei Updates.</p>
      {d.observed === 0 ? <p>Für diese Liga liegen im Zeitraum keine Entscheidungs-Snapshots vor.</p> : <>
        <details><summary>Ausgänge nach Entscheidungsgrund</summary><ul>
          {d.reasons.map(r => <li className="my-2" key={[r.reason,r.category,r.finance].join("/")}>
            {r.reason} · {label(r.category)} · Finanzierung {label(r.finance)} · {r.count} Fälle · Summe {money(r.sum)} · Median {money(r.median)}
          </li>)}
        </ul></details>
        <details><summary>Alternative Gebote</summary><ul>
          {Object.entries(d.bids).map(([k, counts]) => <li className="my-2" key={k}>{label(k)} · {Object.entries(counts).map(([o, n]) => label(o) + " " + n).join(" · ")}</li>)}
        </ul><p>Gewichtete Zuschlagsquote {d.learning.rate === null ? "–" : Math.round(d.learning.rate * 100) + " %"} bei {d.learning.samples} eindeutigen Auktionen.</p></details>
        <details><summary>Alternative Verkäufe · hypothetisch</summary>
          {Object.keys(d.sales).length === 0 && <p>Noch keine auswertbaren Verkaufszeitpunkte.</p>}
          {Object.entries(d.sales).map(([k, v]) => <p key={k}>{label(k)} · {v.count} Fälle · Median {money(v.median)}</p>)}
        </details>
      </>}
    </div>}</QueryState>
  </Card>
}
