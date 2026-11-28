// Mirrors backend/api/schemas.py. Dates arrive as ISO 8601 strings.

export type League = {
  inactive?: boolean
  analysisSquadLimit: number
  analysisClubLimit: number
  id: string
  name: string
  image: string | null
  currentDay: number | null
  numberOfDays: number | null
  seasonName: string | null
  syncedAt: string | null
  marketValuesUpdatedAt: string | null
}

export type User = {
  id: string
  name: string
  image: string | null
}

export type Me = {
  user: User
  /** The viewer's leagues, the preferred one first */
  leagues: League[]
  /** See the other managers estimated balances, see KBI_ALLOW__BALANCES */
  balances: boolean
}

export type SyncRun = {
  id: number
  leagueId: string | null
  trigger: "startup" | "schedule" | "manual" | "login"
  /** Who started a manual sync */
  triggeredBy: string | null
  status: "running" | "success" | "failed"
  startedAt: string
  finishedAt: string | null
  requests: number
  error: string | null
  stats: Record<string, number | string>
}

export type Status = {
  version: string
  demo: boolean
  authenticated: boolean
  league: League | null
  ownManagerId: string | null
  startDate: string | null
  startMoney: number
  sync: {
    running: boolean
    nextRun: string | null
    lastRun: SyncRun | null
    lastSuccessAt: string | null
  }
  /** A match of the current matchday is running, judged by kick-off times */
  liveNow: boolean
  warnings: string[]
}

export type Team = {
  id: string
  name: string
  image: string | null
  placement: number | null
  points: number | null
  matches: number | null
  goalDiff: number | null
}

export type Player = {
  id: string
  firstName: string | null
  lastName: string
  teamId: string | null
  image: string | null
  /** 1 goalkeeper, 2 defender, 3 midfielder, 4 forward */
  position: number
  status: number
  statusText: string | null
  marketValue: number
  /** 0 flat, 1 rising, 2 falling */
  trend: number
  totalPoints: number | null
  averagePoints: number | null
  goals: number | null
  assists: number | null
  active: boolean
  today: number | null
  yesterday: number | null
  twoDays: number | null
  sevenDays: number | null
  thirtyDays: number | null
  ownerId: string | null
  purchasePrice: number | null
  onMarket: boolean
  /** Expected change of the next market value update */
  forecast: number | null
  /** Expected change against today after 1, 2, 3 updates */
  projection: number[]
}

export type BidAdvice = {
  amounts: number[] // suggested bids, lowest first
  comparable: number[] // what other managers paid on top of the mv
  similar: boolean // comparable purchases of a similar market value
}

export type MarketPlayer = Player & {
  sellerId: string | null
  sellerName: string | null
  price: number | null
  offerCount: number | null
  ownBid: number | null
  expiresAt: string | null
  listedAt: string | null
  isFreeAgent: boolean
  bidAdvice: BidAdvice | null // Only for Kickbase's own listings
  /** Managers who may still buy a player of this club, the richest first */
  rivals: Rival[]
  /** Rivals who cannot afford the price are left out as well */
  rivalsByBudget: boolean
  ownClubPlayers: number
  ownClubFull: boolean
  /** Forecast value change until the next deadline, minus the markup on the price */
  marginToMatchday: number | null
  updatesToMatchday: number
  /** Recommended bid: from the league's usual markup up to beating the likely bidders */
  bidLow: number | null
  bidHigh: number | null
  marginLow: number | null
  marginHigh: number | null
  expectedPoints: number | null
  playProbability: number | null
  nextOpponentId: string | null
  nextHome: boolean | null
  /** Home, draw, away of his next match */
  odds: (number | null)[] | null
  sellerInMinus: boolean
}

export type Rival = {
  managerId: string
  name: string
  image: string | null
  clubPlayers: number
  squadSize: number
  estimatedBalance: number | null
  maxBid: number | null
  /** That he bids, from his habits, needs and money */
  probability: number
  expectedBid: number | null
  reasons: string[]
  inMinus: boolean
}

export type WatchedPlayer = Player & {
  expiresAt: string | null // End of the market listing, if there is one
}

export type FairRating = "cheap" | "fair" | "expensive"

export type FairPlayer = Player & {
  games: number
  fairValue: number
  gap: number // Market value against the fair value, -0.3 means 30 % below it
  rating: FairRating
}

export type FairCurvePoint = { points: number; value: number }

export type FairValues = {
  minGames: number // Players need this many games to get a fair value
  band: number // A smaller gap counts as fair
  typicalGap: number | null
  players: FairPlayer[]
  curves: Record<string, FairCurvePoint[]> // By position
}

export type Transfer = {
  id: string
  date: string
  playerId: string
  playerName: string | null
  teamId: string | null
  buyer: string | null
  buyerId: string | null
  seller: string | null
  sellerId: string | null
  price: number
}

export type PlayerDetail = Player & {
  history: [string, number][]
  transfers: Transfer[]
}

export type Manager = {
  id: string
  name: string
  image: string | null
  isSelf: boolean
  placement: number | null
  points: number | null
  pointsBehind: number | null
  averagePoints: number | null
  teamValue: number | null
  matchdayWins: number | null
  budget: number | null
  estimatedBalance: number | null
  maxBid: number | null
  squadSize: number
  transfers: number
  bought: number
  sold: number
  transferProfit: number | null
}

export type Battle = {
  type: number
  name: string
  description: string
  entries: { managerId: string; name: string; image: string | null; placement: number | null; value: number | null }[]
}

export type Turnover = {
  manager: string
  managerId: string | null
  playerId: string
  playerName: string | null
  firstName: string | null
  image: string | null
  teamId: string | null
  position: number | null
  buyPrice: number | null
  buyDate: string | null
  boughtFrom: string | null
  starter: boolean
  sellPrice: number
  sellDate: string
  soldTo: string | null
  profit: number | null
  daysHeld: number | null
}

export type OverpayStats = {
  purchases: number
  /** Paid on top of the market value */
  median: number
  average: number
  total: number
  averageAmount: number // per purchase
  highest: number
}

export type OverpayManager = OverpayStats & { manager: string; managerId: string | null }

export type OverpayPurchase = {
  id: string
  date: string
  manager: string
  managerId: string | null
  playerId: string
  playerName: string | null
  firstName: string | null
  image: string | null
  teamId: string | null
  position: number | null
  price: number
  marketValue: number
  overpay: number
  overpayShare: number
}

export type Overpay = {
  /** Null until the first purchase */
  league: OverpayStats | null
  managers: OverpayManager[]
  purchases: OverpayPurchase[]
}

export type ChartManager = { id: string; name: string }

export type ChartRow = Record<string, number | string | null>

export type RevenueChart = { managers: ChartManager[]; rows: ChartRow[] }

export type MatchdayCharts = {
  managers: ChartManager[]
  teamValues: ChartRow[]
  points: ChartRow[]
  placements: ChartRow[]
}

export type Match = {
  id: string
  day: number
  kickoff: string | null
  team1Id: string | null
  team2Id: string | null
  team1Goals: number | null
  team2Goals: number | null
  status: number | null
  minute: string | null
  state: MatchState
}

export type MatchState = "upcoming" | "running" | "finished"

export type Fixtures = {
  day: number | null
  currentDay: number | null
  numberOfDays: number | null
  matches: Match[]
}

export type LivePlayer = {
  id: string
  firstName: string | null
  lastName: string
  image: string | null
  teamId: string | null
  position: number
  points: number
  matchStatus: number | null
  matchState: MatchState
  matchMinute: string | null
  minute: number | null /** Minutes the player has played, known once the match is finished */
  role: "start" | "sub" | "bench" | null
  onField: boolean
  goals: number
  assists: number
  ownGoals: number
  yellowCards: number
  yellowRedCards: number
  redCards: number
  /** The events summed up per type, the biggest first */
  events: { name: string; count: number; points: number }[]
  /** Every single event in the order of the match */
  timeline: LiveTimelineEvent[]
}

/** Goals, assists and cards. Everything else has no kind. */
export type LiveEventKind = "goal" | "assist" | "own_goal" | "yellow" | "yellow_red" | "red"

export type LiveTimelineEvent = { name: string; points: number; minute: number | null; kind: LiveEventKind | null }

export type LiveManager = {
  id: string
  name: string
  image: string | null
  isSelf: boolean
  matchdayPoints: number
  seasonPoints: number | null
  placement: number | null
  playersStarted: number
  playersOnField: number
  lineupSize: number
  players: LivePlayer[]
}

export type Live = {
  day: number | null
  /** When Kickbase was asked. The server reuses that answer for `cacheSeconds`. */
  updatedAt: string
  cacheSeconds: number
  /** A real match is on. Otherwise the server keeps its last answer until a refresh asks for a new one. */
  matchRunning: boolean
  matches: Match[]
  managers: LiveManager[]
  /** Asked from Kickbase in this round: only players whose match runs or just ended */
  fetchedPlayers: number
  /** No answer from Kickbase, their last known points are shown */
  stalePlayers: number
  /** No answer and nothing known yet, those managers show Kickbase's lagging total */
  missingPlayers: number
}

export type SyncTrigger = { started: boolean; reason: string | null }

/** Every manager's starting eleven of the current matchday, by manager id */
export type Lineups = { day: number | null; lineups: Record<string, string[]> }

/** A match of a player, from their club's point of view */
export type PlayerMatch = {
  day: number | null
  kickoff: string | null
  opponentId: string | null
  home: boolean
  /** Goals of the player's club */
  goals: number | null
  opponentGoals: number | null
  /** Null when the player did not play or the match is still to come */
  points: number | null
  minutes: number | null
  role: "start" | "sub" | "bench" | null
  state: MatchState
  /** The current matchday */
  current: boolean
}

export type PlayerMatches = { season: string | null; matches: PlayerMatch[] }

export type BidResult = { ownBid: number | null }

// ---------------------------------------------------------------------------
// Manager tools
// ---------------------------------------------------------------------------

export type Expectation = {
  playerId: string
  expected: number
  form: number | null
  seasonAverage: number | null
  availability: number
  opponentFactor: number
  opponentId: string | null
  home: boolean | null
  playProbability: number | null
  winProbability: number | null
  reasons: string[]
}

export type SquadPlayer = {
  id: string
  firstName: string | null
  lastName: string
  teamId: string | null
  image: string | null
  position: number
  status: number
  statusText: string | null
  marketValue: number
  averagePoints: number | null
  purchasePrice: number | null
  expected: Expectation
  inLineup: boolean
  inBest: boolean
  forecast: number | null
}

export type Check = { level: "ok" | "info" | "warn" | "error"; message: string }

export type Coach = {
  matchday: { day: number; firstKickoff: string; deadline: string } | null
  liveDay: number | null
  lineupOpen: boolean
  budget: number | null
  squad: SquadPlayer[]
  savedFormation: string | null
  savedLineup: string[]
  savedExpected: number
  bestFormation: string
  bestLineup: string[]
  bestExpected: number
  rescue: {
    sales: string[]
    budgetAfter: number
    expectedBefore: number
    expectedAfter: number
    expectedLoss: number
    enough: boolean
  } | null
  checks: Check[]
  lineupSource: "kickbase" | "ranking"
  sellAdvice: { playerId: string; reason: string; expectedDrop: number; inBest: boolean }[]
  leagueForecast: {
    managerId: string
    name: string
    image: string | null
    isSelf: boolean
    expected: number
    fielded: number
    unavailable: number
  }[]
  updatesToMatchday: number
  sellRatio: number | null
}

export type LineupApplied = { formation: string; playerIds: string[]; confirmed: boolean; response: string | null }
export type SellResult = { playerId: string; budget: number | null; response: string | null }

export type AutomationSettings = {
  autoScout: boolean
  scoutThreshold: number
  scoutLimit: number
  autoLineup: boolean
  deadlineAlerts: boolean
  listingAlerts: boolean
  sellAlerts: boolean
  trader: boolean
  traderLive: boolean
  traderProfit: boolean
  traderOptions: TraderOptions
  sessionExpiresAt?: string | null
  usesServiceAccount?: boolean
  traderOnServer?: boolean
}

export type TraderOptions = {
  snapshotDays: number
  snapshotLimit: number
  minGain: number
  maxCostPerPoint: number
  minAvgEdge: number
  minPlay: number
  lineupShare: number
  profitShare: number
  reserve: number
  coverMaxPrice: number
  dailyBids: number
  dailySales: number
  stopLoss: number
  sellWindow: number
  starterLock: number
  minRoi: number
  creditMode: number
  trailingStop: number
  positionStop: number
  maxHoldDays: number
  shadow: boolean
  rescueOverride: boolean
  sellRatio: number
  upgradeCrossPosition: boolean
  benchStrategy: number
}

export type Shadow = {
  id: number
  at: string
  playerId: string
  name: string | null
  kind: "buy" | "sell"
  purpose: string
  status: "watching" | "holding" | "lost" | "expired" | "done" | string
  bid: number
  marketValue: number
  winnerPrice: number | null
  valueAfter: number | null
  result: number | null
}

export type TraderWeek = {
  week: string
  planned: number
  bids: number
  won: number
  lost: number
  sales: number
  spent: number
  received: number
  profit: number
  pointsGain: number
  shadowTrades: number
  shadowProfit: number
}

export type Trade = {
  id: number
  at: string
  playerId: string
  name: string | null
  kind: "bid" | "sell"
  purpose: "lineup" | "profit" | "room" | "rescue" | "turn" | string
  status: "planned" | "open" | "won" | "lost" | "expired" | "sold" | string
  price: number
  marketValue: number
  paid: number | null
  profit: number | null
  pointsGain: number
  reason: string | null
}

export type Trader = {
  weeks: TraderWeek[]
  trades: Trade[]
  shadows: Shadow[]
  shadowSummary: { open: number; done: number; profit: number; hitRate: number | null; soldThenRose: number | null }
  learned: {
    extra: number[]
    minMargin: number
    won: number
    lost: number
    shadowWon: number
    shadowLost: number
    gainScale: number
    gainSamples: number
    swapEdge: number
    regretSamples: number
    directionRate: number | null
    forecastPaused: boolean
  }
  paused: boolean
  pauseReason: string | null
  enabledOnServer: boolean
}

export type AutomationEvent = {
  id: number
  at: string
  kind: "lineup" | "scout" | "alert" | "sell" | "push" | string
  ok: boolean
  message: string
  details: Record<string, unknown>
}

export type ScoutRun = { added: string[]; removed: string[]; flagged: string[] }

export type ForecastQuality = {
  weights: number[]
  features: string[]
  learned: boolean
  trainingRows: number
  error: number | null
  naiveError: number | null
  checked: number
  directionHits: number | null
  meanAbsError: number | null
  flagPrecision: number | null
}

export type PushKey = { publicKey: string | null; subscribed: number }

export type LostAuction = {
  playerId: string
  playerName: string | null
  date: string
  ownBid: number
  price: number
  winnerId: string
  winner: string
}

export type RivalProfile = {
  id: string
  name: string
  image: string | null
  isSelf: boolean
  squadSize: number
  /** Fit players per position, keys "1"–"4" */
  fitPositions: Record<string, number>
  needs: number[]
  unavailable: string[]
  blockedClubs: string[]
  purchases: number
  purchasesRecent: number
  overpayMedian: number | null
  overpayByClass: (number | null)[]
  activeHours: number[]
  lastActivity: string | null
  estimatedBalance: number | null
  maxBid: number | null
  inMinus: boolean
  balanceHistory: { date: string; balance: number }[]
  lostTo: LostAuction[]
}

export type Rivals = {
  leagueOverpayByClass: (number | null)[]
  priceClasses: number[]
  deadline: string | null
  managers: RivalProfile[]
  lost: LostAuction[]
}

export type BuyOption = {
  player: MarketPlayer
  bid: number
  margin: number | null
  pointsGain: number
  blocked: string | null
}

export type ManagerSquadPlayer = Player & {
  inLineup: boolean
  /** (matchday, points) of the club's last five matches, oldest first. Points null: did not play */
  form: [number, number | null][]
  starts: number | null
  dayPoints: number | null
}

export type ValueSplit = { teamValue: number; today: number }

export type Achievement = {
  key: string
  group: string
  name: string
  description: string
  reward: number
  kind: "each" | "milestone" | "once_per_league"
  count: number | null
  amount: number
}

export type ManagerDetail = {
  id: string
  name: string
  image: string | null
  isSelf: boolean
  placement: number | null
  points: number | null
  previousId: string | null
  nextId: string | null
  transfers: number
  squadSize: number
  maxSquad: number
  total: ValueSplit
  lineup: ValueSplit
  bench: ValueSplit
  transferProfit: number
  overpayAverage: number | null
  clubs: [string, number][]
  positions: Record<string, number>
  estimatedBalance: number | null
  maxBid: number | null
  lineupDay: number | null
  lineupIds: string[]
  days: number[]
  squad: ManagerSquadPlayer[]
  turnovers: Turnover[]
  transferList: Transfer[]
  achievements: Achievement[]
  achievementsTotal: number
  season: { day: number; points: number | null; seasonPoints: number | null; placement: number | null }[]
  teamValues: [string, number][]
  matchdayDates: [number, string][]
}

export type Learning = {
  expectation: {
    form?: number
    average?: number
    win?: number
    table?: number
    rows?: number
    error?: number | null
    defaultError?: number | null
    loggedRows?: number
    historyRows?: number
  }
  expectationLogged: number
  expectationChecked: number
  bidder: { weights?: number[]; bias?: number; auctions?: number }
  auctionsLogged: number
  auctionsResolved: number
  achievementMode: { mode?: "matchday" | "player"; votesMatchday?: number; votesPlayer?: number }
  sellRatio: { ratio?: number; sales?: number }
  balanceCorrection: { amount: number; members: number; residuals: number[] } | null
  achievements: { key: string; name: string; kickbase: number | null; app: number | null }[]
  achievementsCheckedAt: string | null
}
