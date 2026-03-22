/**
 * Shared TypeScript types used across frontend pages.
 *
 * Centralised here to avoid duplication and keep page files lean.
 */

// ── Anime / MAL ─────────────────────────────────────

export interface AnimeEntry {
  mal_anime_id: number;
  title: string;
  title_english: string | null;
  image_url: string | null;
  watch_status: string;
  user_score: number;
  episodes_watched: number;
  total_episodes: number | null;
  anime_type: string | null;
  genres: string | null;
  themes: string | null;
  year: number | null;
  mal_score: number | null;
}

export interface MALSyncStatus {
  anime_list_id?: string;
  mal_username: string | null;
  sync_status: string; // pending | in_progress | completed | failed
  total_entries: number;
  last_synced_at?: string | null;
  source?: string; // "mal" | "anilist" — actual source of the current list
}

export interface AniListImportResponse {
  anime_list_id: string;
  anilist_username: string;
  sync_status: string;
  message: string;
}

export interface AniListSyncStatus {
  anime_list_id?: string;
  anilist_username: string | null;
  sync_status: string; // pending | in_progress | completed | failed
  total_entries: number;
  skipped_no_mal_id: number;
  last_synced_at?: string | null;
  source?: string; // always "anilist"
}

// ── Recommendations ─────────────────────────────────

export interface RecommendationItem {
  mal_id: number;
  title: string;
  image_url: string | null;
  genres: string;
  themes: string;
  synopsis: string;
  mal_score: number | null;
  year: number | null;
  anime_type: string | null;
  reasoning: string;
  confidence: "high" | "medium" | "low";
  similar_to: string[];
  similarity_score: number;
  preference_score: number;
  combined_score: number;
  is_fallback: boolean;
}

export interface RecommendationResponse {
  recommendations: RecommendationItem[];
  generated_at: string;
  total: number;
  used_fallback: boolean;
  custom_query: string | null;
}

export interface RecommendationGenerateAccepted {
  job_id: string;
  status: "queued" | "running" | "succeeded" | "failed";
  progress: number;
  stage: string;
}

export interface RecommendationJobStatus {
  job_id: string;
  status: "queued" | "running" | "succeeded" | "failed";
  progress: number;
  stage: string;
  error: string | null;
  session_id: string | null;
}

export interface SessionSummary {
  id: string;
  generated_at: string;
  custom_query: string | null;
  total_count: number;
  used_fallback: boolean;
}

export interface HistoryResponse {
  sessions: SessionSummary[];
  total: number;
}

export interface FeedbackMapResponse {
  feedback: Record<number, string>;
}

export interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
    details?: unknown;
    request_id?: string;
  };
}

// ── Watchlist ───────────────────────────────────────

export interface WatchlistItem {
  id: string;
  mal_id: number;
  title: string;
  image_url: string | null;
  genres: string | null;
  themes: string | null;
  mal_score: number | null;
  year: number | null;
  anime_type: string | null;
  status: string;
  user_rating: number | null;
  reaction: string | null;
  source: string;
  notes: string | null;
  added_at: string;
}

export interface WatchlistResponse {
  items: WatchlistItem[];
  total: number;
}

// ── Dashboard / Preference Profile ──────────────────

export interface GenreAffinity {
  genre: string;
  count: number;
  avg_score: number;
  affinity: number;
}

export interface PreferenceProfile {
  total_watched: number;
  total_scored: number;
  mean_score: number;
  score_distribution: Record<string, number>;
  genre_affinity: GenreAffinity[];
  theme_affinity: GenreAffinity[];
  studio_affinity: GenreAffinity[];
  preferred_formats: Record<string, number>;
  completion_rate: number;
  top_10: AnimeEntry[];
  watch_era_preference: Record<string, number>;
  generated_at: string;
  source?: string | null; // "mal" | "anilist"
  imported_username?: string | null;
}

// ── Cauldron ─────────────────────────────────────────

export interface CauldronSearchResult {
  mal_id: number;
  title: string;
  title_english: string | null;
  image_url: string | null;
  year: number | null;
  anime_type: string | null;
  genres: string | null;
  mal_score: number | null;
}

export interface CauldronSearchResponse {
  results: CauldronSearchResult[];
  total: number;
}

export interface CauldronResultsResponse {
  session_id: string;
  seed_titles: string[];
  recommendations: RecommendationItem[];
  generated_at: string;
  total: number;
  used_fallback: boolean;
}

// ── MAL Import ──────────────────────────────────────

export interface MALImportResponse {
  anime_list_id: string;
  mal_username: string;
  sync_status: string;
  message: string;
}
