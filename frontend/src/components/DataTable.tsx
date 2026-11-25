/**
 * DataTable component for displaying tabular data with sorting, mobile view, and customizable columns.
*/

import {
  type CellContext,
  type ColumnDef,
  type RowData,
  type SortingState,
  type Table,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table"
import { ArrowDown, ArrowDownUp, ArrowUp } from "lucide-react"
import { type ReactNode, useEffect, useLayoutEffect, useState } from "react"
import { cn } from "@/lib/cn"
import { Button, EmptyState } from "./ui"

declare module "@tanstack/react-table" {
  interface ColumnMeta<TData extends RowData, TValue> {
    align?: "left" | "right" | "center"
    /** Hide the column below this breakpoint */
    hideBelow?: "sm" | "md" | "lg" | "xl" | "2xl" | "3xl"
    className?: string
  }
}

// Spelled out, so Tailwind's scanner finds every class
const HIDE: Record<string, string> = {
  sm: "hidden sm:table-cell",
  md: "hidden md:table-cell",
  lg: "hidden lg:table-cell",
  xl: "hidden xl:table-cell",
  "2xl": "hidden 2xl:table-cell",
  "3xl": "hidden 3xl:table-cell",
}
const ALIGN: Record<string, string> = { left: "text-left", right: "text-right", center: "text-center" }

type Props<T> = {
  data: T[]
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  columns: ColumnDef<T, any>[]
  initialSorting?: SortingState
  getRowId?: (row: T) => string
  onRowClick?: (row: T) => void
  rowClassName?: (row: T) => string | undefined | false
  /** Rendered instead of the table on small screens */
  mobileCard?: (row: T) => ReactNode
  pageSize?: number
  empty?: ReactNode
  className?: string
}

export function DataTable<T>({
  data,
  columns,
  initialSorting = [],
  getRowId,
  onRowClick,
  rowClassName,
  mobileCard,
  pageSize = 50,
  empty,
  className,
}: Props<T>) {
  const [sorting, setSorting] = useState<SortingState>(initialSorting)
  const [visible, setVisible] = useState(pageSize)
  const fit = useFitColumns(columns)

  // A new filter result starts at the first page again
  useEffect(() => setVisible(pageSize), [data, pageSize])

  const table = useReactTable({
    data,
    columns,
    state: { sorting, columnVisibility: fit.hidden },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId,
  })

  const rows = table.getRowModel().rows
  if (rows.length === 0) return <>{empty ?? <EmptyState title="Keine Einträge gefunden" />}</>
  const shown = rows.slice(0, visible)
  // Cards also on wider screens when the table cannot fit even without its optional columns
  const cards = !!mobileCard && fit.tooNarrow

  return (
    <div ref={fit.outerRef} className={className}>
      {mobileCard && (
        <div className={cards ? undefined : "md:hidden"}>
          <MobileSort table={table} />
          <ul className="divide-y divide-line border-t border-line">
            {shown.map((row) => (
              <li
                key={row.id}
                onClick={onRowClick ? () => onRowClick(row.original) : undefined}
                className={cn("px-4 py-3", onRowClick && "cursor-pointer active:bg-surface-2", rowClassName?.(row.original))}
              >
                {mobileCard(row.original)}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div ref={fit.ref} className={cn("overflow-x-auto", cards ? "hidden" : mobileCard && "hidden md:block")}>
        <table className="w-full border-collapse text-sm">
          <thead>
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id} className="border-y border-line bg-surface-2/60">
                {group.headers.map((header) => {
                  const meta = header.column.columnDef.meta
                  const sorted = header.column.getIsSorted()
                  const canSort = header.column.getCanSort()
                  return (
                    <th
                      key={header.id}
                      scope="col"
                      aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : undefined}
                      className={cn(
                        "px-3 py-2.5 text-xs font-medium whitespace-nowrap text-muted first:pl-4 last:pr-4 sm:first:pl-5 sm:last:pr-5",
                        ALIGN[meta?.align ?? "left"],
                        meta?.hideBelow && HIDE[meta.hideBelow],
                        meta?.className,
                      )}
                    >
                      {canSort ? (
                        <button
                          type="button"
                          onClick={header.column.getToggleSortingHandler()}
                          className={cn(
                            "inline-flex items-center gap-1 hover:text-fg",
                            meta?.align === "right" && "flex-row-reverse text-right",
                            sorted && "text-fg",
                          )}
                        >
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          {sorted === "asc" ? (
                            <ArrowUp className="size-3.5 shrink-0" />
                          ) : sorted === "desc" ? (
                            <ArrowDown className="size-3.5 shrink-0" />
                          ) : (
                            <ArrowDownUp className="size-3.5 shrink-0 opacity-40" />
                          )}
                        </button>
                      ) : (
                        flexRender(header.column.columnDef.header, header.getContext())
                      )}
                    </th>
                  )
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {shown.map((row) => (
              <tr
                key={row.id}
                onClick={onRowClick ? () => onRowClick(row.original) : undefined}
                className={cn(
                  "border-b border-line last:border-b-0",
                  onRowClick && "cursor-pointer hover:bg-surface-2/70",
                  rowClassName?.(row.original),
                )}
              >
                {row.getVisibleCells().map((cell) => {
                  const meta = cell.column.columnDef.meta
                  return (
                    <td
                      key={cell.id}
                      className={cn(
                        "px-3 py-2.5 whitespace-nowrap first:pl-4 last:pr-4 sm:first:pl-5 sm:last:pr-5",
                        ALIGN[meta?.align ?? "left"],
                        meta?.hideBelow && HIDE[meta.hideBelow],
                        meta?.className,
                      )}
                    >
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {rows.length > visible && (
        <div className="border-t border-line p-3 text-center">
          <Button size="sm" onClick={() => setVisible((v) => v + pageSize)}>
            Mehr anzeigen <span className="text-muted">({rows.length - visible} weitere)</span>
          </Button>
        </div>
      )}
    </div>
  )
}

const RANK = ["sm", "md", "lg", "xl", "2xl", "3xl"]

/**
 * Hides the optional columns (those with `hideBelow`), the least important first, until the table fits
 * its box, so it never needs a horizontal scrollbar while there is something left to drop. The box's
 * width, not the window's, decides: the sidebar and side by side cards take their share.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function useFitColumns<T>(columns: ColumnDef<T, any>[]) {
  const [element, setElement] = useState<HTMLDivElement | null>(null)
  const [outer, setOuter] = useState<HTMLDivElement | null>(null)
  const [count, setCount] = useState(0)
  const [width, setWidth] = useState(0)
  // The narrowest the table gets with every optional column gone; below it the cards take over
  const [need, setNeed] = useState(0)
  const order = columns
    .map((column, index) => ({ id: column.id ?? (column as { accessorKey?: string }).accessorKey, rank: RANK.indexOf(column.meta?.hideBelow ?? ""), index }))
    .filter((c): c is { id: string; rank: number; index: number } => !!c.id && c.rank >= 0)
    .sort((a, b) => b.rank - a.rank || b.index - a.index)
    .map((c) => c.id)

  // A wider box may fit more again: start over and drop again below
  useEffect(() => {
    if (!outer) return
    const observer = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)))
    observer.observe(outer)
    return () => observer.disconnect()
  }, [outer])
  useLayoutEffect(() => setCount(0), [width])
  useLayoutEffect(() => {
    if (!element || element.scrollWidth <= element.clientWidth + 1) return
    if (count < order.length) setCount(count + 1)
    else if (element.scrollWidth !== need) setNeed(element.scrollWidth)
  })

  const hidden = Object.fromEntries(order.slice(0, count).map((id) => [id, false]))
  return { ref: setElement, outerRef: setOuter, hidden, tooNarrow: width > 0 && need > width }
}

function MobileSort<T>({ table }: { table: Table<T> }) {
  const sortable = table.getAllLeafColumns().filter((column) => column.getCanSort() && typeof column.columnDef.header === "string")
  if (sortable.length === 0) return null
  const current = table.getState().sorting[0]
  return (
    <div className="flex items-center gap-2 px-4 pb-3">
      <span className="text-xs text-muted">Sortieren</span>
      <select
        value={current?.id ?? ""}
        onChange={(event) =>
          table.setSorting(event.target.value ? [{ id: event.target.value, desc: current?.desc ?? true }] : [])
        }
        className="h-8 min-w-0 flex-1 rounded-lg border border-line bg-surface px-2 text-sm"
      >
        <option value="">Standard</option>
        {sortable.map((column) => (
          <option key={column.id} value={column.id}>
            {column.columnDef.header as string}
          </option>
        ))}
      </select>
      <button
        type="button"
        disabled={!current}
        onClick={() => current && table.setSorting([{ id: current.id, desc: !current.desc }])}
        aria-label={current?.desc ? "Absteigend" : "Aufsteigend"}
        className="grid size-8 place-items-center rounded-lg border border-line disabled:opacity-40"
      >
        {current?.desc === false ? <ArrowUp className="size-4" /> : <ArrowDown className="size-4" />}
      </button>
    </div>
  )
}

/** A right aligned numeric column. Missing values sort last in both directions. */
export function numberColumn<T>(
  id: string,
  header: string,
  get: (row: T) => number | null | undefined,
  cell: (value: number | undefined, row: T) => ReactNode,
  meta: ColumnDef<T>["meta"] = {},
): ColumnDef<T, number | undefined> {
  return {
    id,
    header,
    accessorFn: (row) => get(row) ?? undefined,
    cell: (ctx: CellContext<T, number | undefined>) => cell(ctx.getValue(), ctx.row.original),
    sortUndefined: "last",
    sortDescFirst: true,
    meta: { align: "right", ...meta },
  }
}
