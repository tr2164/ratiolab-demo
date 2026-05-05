import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

function getApiErrorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (detail) return JSON.stringify(detail)
    return err.message
  }
  return err instanceof Error ? err.message : 'Request failed'
}

export interface XBRLValue {
  xbrl_concept: string
  values: Record<number, number>
}

export interface UsefulLife {
  asset_type: string
  xbrl_member: string
  xbrl_concept: string
  useful_life_min: number | null
  useful_life_max: number | null
  useful_life_raw_min: string | null
  useful_life_raw_max: string | null
}

export interface DisclosureBlock {
  xbrl_concept: string
  html: string
  text: string
  period: string
  fiscal_year: number | null
}

export interface CompanyInfo {
  name: string
  ticker: string
  cik: string
  form: string
  filing_date: string
}

export interface PPESegment {
  segment_label: string
  xbrl_member: string
  xbrl_concept: string
  dimension_axis: string
  values: Record<number, number>
}

export interface PPEData {
  company: CompanyInfo
  totals: Record<string, XBRLValue>
  useful_lives: UsefulLife[]
  disclosure_blocks: DisclosureBlock[]
  historical: Record<string, Record<number, number>>
  segments: PPESegment[]
}

export interface SingleFact {
  xbrl_concept: string
  values: Record<number, number>
  label: string
}

export async function fetchPPE(ticker: string): Promise<PPEData> {
  const { data } = await api.get<PPEData>(`/ppe/${ticker}`)
  return data
}

export async function fetchSingleFact(ticker: string, concept: string, module: string = 'ppe'): Promise<SingleFact> {
  const { data } = await api.get<SingleFact>(`/${module}/${ticker}/fact/${encodeURIComponent(concept)}`)
  return data
}

export interface Observation {
  title: string
  insight: string
  follow_up: string
}

export interface DisclosureAnalysis {
  depreciation_method: string
  capitalization_policy: string
  policy_highlights: string[]
  asset_age_pct: number | null
  observations: Observation[]
  summary: string
}

export async function analyzeDisclosure(ticker: string, layer: number = 2, segment?: string): Promise<DisclosureAnalysis> {
  const params: Record<string, string | number> = { layer }
  if (segment) params.segment = segment
  const { data } = await api.get<DisclosureAnalysis>(`/ppe/${ticker}/analyze`, {
    params,
    timeout: 60000,
  })
  return data
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export async function chatAboutPPE(ticker: string, messages: ChatMessage[]): Promise<ChatMessage> {
  const { data } = await api.post<ChatMessage>(`/ppe/${ticker}/chat`, { messages }, { timeout: 60000 })
  return data
}

export interface TagSearchResult {
  tag: string
  label: string
  has_numeric_values: boolean
}

export interface TagSearchResponse {
  query: string
  count: number
  tags: TagSearchResult[]
}

// ---- Company Ticker Search ----

export interface TickerResult {
  cik: number
  ticker: string
  title: string
}

export async function searchTickers(query: string): Promise<TickerResult[]> {
  const { data } = await api.get<TickerResult[]>(`/tickers/search`, {
    params: { q: query, limit: 15 },
  })
  return data
}

export async function searchXbrlTags(ticker: string, q: string, module: string = 'ppe'): Promise<TagSearchResponse> {
  const { data } = await api.get<TagSearchResponse>(`/${module}/${ticker}/search-tags`, {
    params: { q, limit: 30 },
  })
  return data
}

// ---- Comparables (Layer 4) ----

export interface PeerSummary {
  company: CompanyInfo
  gross: number | null
  accumulated_depreciation: number | null
  net: number | null
  asset_age_pct: number | null
  avg_useful_life: number | null
  useful_life_range: (number | null)[]
  yoy_net_growth: number | null
  depreciation_method: string
  error: string | null
}

export async function fetchPeerComparables(tickers: string[]): Promise<PeerSummary[]> {
  const { data } = await api.post<{ peers: PeerSummary[] }>('/ppe/compare', { tickers }, { timeout: 120000 })
  return data.peers
}


// =========================================================================
// Allowance for Doubtful Accounts Module
// =========================================================================

export interface ReceivableSegment {
  segment_label: string
  xbrl_member: string
  xbrl_concept: string
  dimension_axis: string
  values: Record<number, number>
}

export interface AllowanceData {
  company: CompanyInfo
  totals: Record<string, XBRLValue>
  computed: Record<string, Record<number, number | null>>
  disclosure_blocks: DisclosureBlock[]
  historical: Record<string, Record<number, number>>
  rollforward: Record<string, Record<number, number>> | null
  receivable_segments: ReceivableSegment[]
}

export interface AllowanceAnalysis {
  allowance_methodology: string
  risk_factors: string
  policy_highlights: string[]
  allowance_ratio_pct: number | null
  observations: Observation[]
  summary: string
}

export interface ForensicFlag {
  severity: 'red' | 'yellow' | 'green'
  flag: string
  detail: string
  year: number | null
}

export interface ForensicResult {
  flags: ForensicFlag[]
  summary: string
}

export interface SensitivityResult {
  gross_ar: number
  current_allowance: number
  current_ratio: number
  scenario_ratio: number
  scenario_allowance: number
  bad_debt_expense_change: number
  pre_tax_income_impact: number
  after_tax_income_impact: number
}

export interface PeerSegmentSummary {
  segment_label: string
  xbrl_member: string
  latest_value: number | null
  pct_of_total: number | null
}

export interface AllowancePeerSummary {
  company: CompanyInfo
  ar_net: number | null
  allowance: number | null
  gross_ar: number | null
  allowance_ratio: number | null
  bad_debt_expense: number | null
  revenue: number | null
  bad_debt_to_revenue: number | null
  dso: number | null
  yoy_ratio_change: number | null
  segments: PeerSegmentSummary[]
  dominant_segment: string | null
  dominant_segment_ar: number | null
  dominant_segment_ratio: number | null
  error: string | null
}

export async function fetchAllowance(ticker: string): Promise<AllowanceData> {
  const { data } = await api.get<AllowanceData>(`/allowance/${ticker}`)
  return data
}

export async function analyzeAllowance(ticker: string, layer: number = 1, segment?: string): Promise<AllowanceAnalysis> {
  const params: Record<string, string | number> = { layer }
  if (segment) params.segment = segment
  const { data } = await api.get<AllowanceAnalysis>(`/allowance/${ticker}/analyze`, {
    params,
    timeout: 60000,
  })
  return data
}

export async function chatAboutAllowance(ticker: string, messages: ChatMessage[]): Promise<ChatMessage> {
  const { data } = await api.post<ChatMessage>(`/allowance/${ticker}/chat`, { messages }, { timeout: 60000 })
  return data
}

export async function fetchForensics(ticker: string): Promise<ForensicResult> {
  const { data } = await api.get<ForensicResult>(`/allowance/${ticker}/forensics`, { timeout: 60000 })
  return data
}

export async function runSensitivity(params: {
  gross_ar: number; current_ratio: number; scenario_ratio: number; tax_rate?: number
}): Promise<SensitivityResult> {
  const { data } = await api.post<SensitivityResult>('/allowance/sensitivity', params, { timeout: 10000 })
  return data
}

export async function fetchAllowancePeerComparables(tickers: string[]): Promise<AllowancePeerSummary[]> {
  const { data } = await api.post<{ peers: AllowancePeerSummary[] }>('/allowance/compare', { tickers }, { timeout: 120000 })
  return data.peers
}


// =========================================================================
// Ratio Lab Module
// =========================================================================

export interface StatementLineItem {
  concept: string
  label: string
  category: string
  unit: string
  years_available: number
  latest_value: number | null
  is_instant: boolean
}

export interface StatementCompanyInfo {
  name: string
  ticker: string
  cik: string
  form: string
  filing_date: string
}

export interface LineItemCatalog {
  company: StatementCompanyInfo
  items: StatementLineItem[]
  category_counts: Record<string, number>
}

export interface LineItemDataResult {
  concept: string
  label: string
  values: Record<number, number>
}

export interface LineItemDataResponse {
  company_name: string
  ticker: string
  items: LineItemDataResult[]
}

export interface FootnoteBlock {
  xbrl_concept: string
  html: string
  text: string
  period: string
  fiscal_year: number | null
  matched_keyword: string
}

export interface FootnoteResponse {
  company_name: string
  ticker: string
  blocks: FootnoteBlock[]
}

export interface RatioTerm {
  concept: string
  sign: string
}

export interface RatioDefinition {
  name: string
  numerator_terms: RatioTerm[]
  denominator_terms: RatioTerm[]
  multiply_by: number
}

export interface RatioResultItem {
  name: string
  definition: RatioDefinition
  values: Record<number, number | null>
  trend: string
}

export interface RatioResponse {
  company_name: string
  ticker: string
  results: RatioResultItem[]
}

export interface RatioTemplate {
  name: string
  category: string
  numerator_terms: RatioTerm[]
  denominator_terms: RatioTerm[]
  multiply_by: number
  available?: boolean
  missing_concepts?: string[]
}

export interface RatioObservation {
  title: string
  insight: string
  follow_up: string
}

export interface RatioAnalysisResult {
  ratio_highlights: string[]
  observations: RatioObservation[]
  summary: string
}

export async function fetchLineItems(ticker: string, category?: string, q?: string): Promise<LineItemCatalog> {
  const params: Record<string, string> = {}
  if (category) params.category = category
  if (q) params.q = q
  const { data } = await api.get<LineItemCatalog>(`/statements/${ticker}/line-items`, { params, timeout: 30000 })
  return data
}

export async function fetchLineItemData(ticker: string, concepts: string[]): Promise<LineItemDataResponse> {
  const { data } = await api.post<LineItemDataResponse>(`/statements/${ticker}/data`, { concepts }, { timeout: 30000 })
  return data
}

export async function fetchStatementFootnotes(ticker: string, concepts: string[]): Promise<FootnoteResponse> {
  const { data } = await api.post<FootnoteResponse>(`/statements/${ticker}/footnotes`, { concepts }, { timeout: 60000 })
  return data
}

export async function computeRatios(ticker: string, ratios: RatioDefinition[]): Promise<RatioResponse> {
  const { data } = await api.post<RatioResponse>(`/statements/${ticker}/ratios`, { ratios }, { timeout: 30000 })
  return data
}

export async function fetchRatioTemplates(ticker?: string): Promise<RatioTemplate[]> {
  const url = ticker ? `/statements/${ticker}/templates` : '/statements/templates'
  const { data } = await api.get<{ templates: RatioTemplate[] }>(url, { timeout: 15000 })
  return data.templates
}

export async function analyzeRatios(ticker: string, ratioResults: RatioResultItem[]): Promise<RatioAnalysisResult> {
  const ratiosJson = JSON.stringify(ratioResults.map(r => ({
    name: r.name,
    values: r.values,
    trend: r.trend,
  })))
  try {
    const { data } = await api.get<RatioAnalysisResult>(`/statements/${ticker}/analyze`, {
      params: { ratios_json: ratiosJson },
      timeout: 60000,
    })
    return data
  } catch (err) {
    throw new Error(getApiErrorMessage(err))
  }
}

export async function chatAboutRatios(
  ticker: string,
  messages: ChatMessage[],
  ratioContext?: string,
  contextType?: 'ratios' | 'disclosure',
): Promise<ChatMessage> {
  const { data } = await api.post<ChatMessage>(
    `/statements/${ticker}/chat`,
    { messages, ratio_context: ratioContext, context_type: contextType ?? 'ratios' },
    { timeout: 60000 },
  )
  return data
}


// =========================================================================
// Analyst Call Reviewer Module
// =========================================================================

export interface TranscriptFile {
  filename: string
  ticker: string
  quarter: string
  fiscal_year: number
  call_date: string
  doc_type: string
  word_count: number
  page_count: number
}

export interface TranscriptSection {
  section_type: string   // "prepared_remarks" | "qa"
  speaker: string
  role: string           // "management" | "analyst" | "operator"
  text: string
  word_count: number
}

export interface ParsedTranscript {
  meta: TranscriptFile
  sections: TranscriptSection[]
  full_text: string
  management_speakers: string[]
  analyst_count: number
  prepared_word_count: number
  qa_word_count: number
}

export interface TranscriptListResponse {
  ticker: string
  transcripts: TranscriptFile[]
  releases: TranscriptFile[]
  other: TranscriptFile[]
}

export interface KeywordHit {
  keyword: string
  category: string
  count: number
  sentiment: string
}

export interface TopicBreakdown {
  topic: string
  pct: number
  sample_quote: string
}

export interface SentimentAnalysis {
  overall_label: string
  overall_score: number
  management_confidence: number
  hedge_density: number
  key_quotes: string[]
  guidance_statements: string[]
  top_topics: TopicBreakdown[]
  tone_narrative: string
  keywords: KeywordHit[]
  hedge_words_found: string[]
}

export interface FinancialKPI {
  label: string
  value: number | null
  period: string
  unit: string
  yoy_change: number | null
}

export interface ManagementSignal {
  topic: string
  what_was_said: string
  actual_result: string
  alignment: string
}

export interface ComparisonAnalysis {
  transcript_quarter: string
  financial_kpis: FinancialKPI[]
  management_signals: ManagementSignal[]
  beat_miss_summary: string
  ai_comparison: string
  data_source: string
}

export interface EarningsCallObservation {
  title: string
  insight: string
  follow_up: string
}

export interface EarningsCallAnalysis {
  meta: TranscriptFile
  sentiment: SentimentAnalysis
  comparison: ComparisonAnalysis | null
  ai_summary: string
  observations: EarningsCallObservation[]
}

export async function fetchEarningsCallFiles(ticker: string): Promise<TranscriptListResponse> {
  const { data } = await api.get<TranscriptListResponse>(`/earnings-calls/${ticker}/files`)
  return data
}

export interface DiscoveryStep {
  step: string
  status: 'running' | 'done' | 'error' | 'skip'
  detail: string
}

export interface DiscoveryCandidate {
  url: string
  title: string
}

export interface DiscoveryResult {
  ticker: string
  candidates_found: number
  candidates: DiscoveryCandidate[]
  downloaded: { filename: string; url: string; status: string }[]
  steps: DiscoveryStep[]
  message: string
}

export async function searchEarningsCallTranscripts(
  ticker: string,
  opts: { company_name?: string; quarter?: string; year?: number } = {},
): Promise<DiscoveryResult> {
  const { data } = await api.post<DiscoveryResult>(
    `/earnings-calls/${ticker}/search`,
    opts,
    { timeout: 90000 },
  )
  return data
}

export async function uploadEarningsCallTranscript(
  ticker: string,
  file: File,
  docType: string = 'EarningsCall',
): Promise<TranscriptFile> {
  const form = new FormData()
  form.append('file', file)
  form.append('doc_type', docType)
  const { data } = await api.post<TranscriptFile>(
    `/earnings-calls/${ticker}/upload`,
    form,
    { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 30000 },
  )
  return data
}

export async function parseEarningsCallTranscript(ticker: string, filename: string): Promise<ParsedTranscript> {
  const { data } = await api.get<ParsedTranscript>(`/earnings-calls/${ticker}/parse`, {
    params: { filename },
    timeout: 30000,
  })
  return data
}

export async function analyzeEarningsCall(ticker: string, filename: string): Promise<EarningsCallAnalysis> {
  const { data } = await api.get<EarningsCallAnalysis>(`/earnings-calls/${ticker}/analyze`, {
    params: { filename },
    timeout: 120000,
  })
  return data
}

export async function chatAboutEarningsCall(
  ticker: string,
  messages: ChatMessage[],
  transcriptFilename?: string,
): Promise<ChatMessage> {
  const { data } = await api.post<ChatMessage>(
    `/earnings-calls/${ticker}/chat`,
    { messages, transcript_filename: transcriptFilename ?? null },
    { timeout: 60000 },
  )
  return data
}


// ---------------------------------------------------------------------------
// Deep agent — streaming types + helpers
// ---------------------------------------------------------------------------

export interface ClassifiedCandidate {
  url: string
  title: string
  source: 'web' | 'ir_page'
  doc_type: 'earnings_call' | 'analyst_day' | 'investor_day' | 'press_release' | 'annual_report' | 'presentation' | 'other'
  quarter: string | null
  year: number | null
  confidence: number
  reason: string
}

export type DiscoverSSEEvent =
  | { type: 'step'; step: string; status: 'running' | 'done' | 'error' | 'skip'; message: string }
  | { type: 'candidate'; data: ClassifiedCandidate }
  | { type: 'done'; total: number }
  | { type: 'error'; message: string }
  | { type: 'stream_end' }

export type ProcessSSEEvent =
  | { type: 'step'; step: string; status: 'running' | 'done' | 'error'; message: string }
  | { type: 'progress'; bytes_downloaded: number; total_bytes: number | null }
  | { type: 'complete'; filename: string }
  | { type: 'error'; message: string }
  | { type: 'stream_end' }

/** Parse a fetch SSE stream and call onEvent for each data line. */
async function consumeSSE<T>(
  response: Response,
  onEvent: (event: T) => void,
): Promise<void> {
  if (!response.body) throw new Error('No response body')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const raw = line.slice(6).trim()
        if (raw) {
          try { onEvent(JSON.parse(raw) as T) } catch { /* ignore parse errors */ }
        }
      }
    }
  }
}

export async function streamDiscoverTranscripts(
  ticker: string,
  params: { company_name?: string; quarter?: string; year?: number } = {},
  onEvent: (event: DiscoverSSEEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const qs = new URLSearchParams()
  if (params.company_name) qs.set('company_name', params.company_name)
  if (params.quarter) qs.set('quarter', params.quarter)
  if (params.year) qs.set('year', String(params.year))
  const url = `/api/earnings-calls/${ticker}/discover/stream?${qs}`
  const resp = await fetch(url, {
    method: 'GET',
    headers: { Accept: 'text/event-stream' },
    signal,
  })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  await consumeSSE<DiscoverSSEEvent>(resp, onEvent)
}

export async function streamProcessTranscript(
  ticker: string,
  req: { url: string; title?: string },
  onEvent: (event: ProcessSSEEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch(`/api/earnings-calls/${ticker}/process/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ url: req.url, title: req.title ?? '' }),
    signal,
  })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  await consumeSSE<ProcessSSEEvent>(resp, onEvent)
}

// -- Checkpoint Questions --

export interface CheckpointChoice {
  id: string
  text: string
}

export interface CheckpointQuestion {
  id: number
  module: string
  layer: number
  question_type: 'mc' | 'short_answer'
  question_text: string
  choices: CheckpointChoice[] | null
  sort_order: number
}

export interface CheckpointResponseResult {
  id: number
  is_correct: boolean | null
  correct_answer: string | null
  explanation: string | null
}

export async function fetchCheckpointQuestions(
  module: string,
  layer: number,
): Promise<CheckpointQuestion[]> {
  const { data } = await api.get<CheckpointQuestion[]>(`/checkpoints/${module}/${layer}`)
  return data
}

export async function submitCheckpointResponse(
  questionId: number,
  body: { selected_choice?: string; text_response?: string },
): Promise<CheckpointResponseResult> {
  const { data } = await api.post<CheckpointResponseResult>(
    `/checkpoints/${questionId}/respond`,
    body,
  )
  return data
}
