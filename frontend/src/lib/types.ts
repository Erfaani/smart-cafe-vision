/** Shapes returned by the Django API. Kept in one place so a contract change
 *  surfaces as a TypeScript error rather than as an undefined at runtime. */

import type { ColorStop } from "@/lib/stay-color";

export type Role = "owner" | "manager" | "staff" | "viewer";

export interface User {
  id: string;
  email: string;
  full_name: string;
  display_name: string;
  role: Role;
  cafe: string | null;
  cafe_slug: string | null;
  cafe_name: string | null;
  is_active: boolean;
  is_superuser: boolean;
  last_login: string | null;
  date_joined: string;
}

export interface Cafe {
  id: string;
  name: string;
  slug: string;
  logo: string | null;
  timezone: string;
  default_language: "en" | "fa";
  seating_capacity: number;
  is_active: boolean;
  // Phase 6: colour stops for stay-time display -- the single source both
  // this dashboard and (from Phase 7) the public display colour a customer's
  // box/row from. See src/lib/stay-color.ts.
  stay_color_stops: ColorStop[];
  privacy_notice: string;
}

export type ComponentStatus = "ok" | "degraded" | "down";

export interface HealthComponent {
  status: ComponentStatus;
  detail?: string;
  latency_ms?: number;
  stream_length?: number;
  workers?: Array<{
    worker_id: string;
    status: ComponentStatus;
    seconds_since_heartbeat: number;
  }>;
}

export interface HealthReport {
  status: ComponentStatus;
  environment: string;
  version: string;
  components: Record<string, HealthComponent>;
}

export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface ApiError {
  error: { code: string; message: string; detail?: unknown };
}

export interface LoginResponse {
  access: string;
  refresh: string;
  user: User;
}

export type CameraConnectionStatus = "unknown" | "connecting" | "connected" | "disconnected" | "error";
export type CameraTransport = "tcp" | "udp";
export type CameraMountType = "unknown" | "overhead" | "wall";

export interface Camera {
  id: string;
  name: string;
  location: string;
  rtsp_url: string;
  rtsp_username: string;
  has_password: boolean;
  transport: CameraTransport;
  is_enabled: boolean;
  connection_status: CameraConnectionStatus;
  is_stale: boolean;
  last_error: string;
  last_connected_at: string | null;
  last_frame_at: string | null;
  last_fps: number | null;
  resolution_width: number | null;
  resolution_height: number | null;
  // Phase 3: a periodic snapshot from the worker's last detection tick, null
  // in capture-only mode (no model loaded, or AI_DETECTION_ENABLED=false).
  last_person_count: number | null;
  last_inference_ms: number | null;
  // Phase 4: the tracker's considered view as of the same snapshot -- can
  // legitimately differ from last_person_count (a briefly-occluded person the
  // tracker still counts through the gap). Null whenever tracking isn't
  // running (no detector loaded, or the tracker itself failed to build).
  last_track_count: number | null;
  // Phase 9: admin-entered, not observed -- affects how confidently table
  // occupancy is reported for this camera's tables. "unknown" (the default)
  // gets the same honest, conservative caveat as "wall".
  mount_type: CameraMountType;
  created_at: string;
  updated_at: string;
}

export interface CameraTestConnectionResult {
  status: string;
  ok: boolean;
  message: string;
  detail?: string;
}

export interface DetectionBox {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  confidence: number;
}

/** Near-real-time, not the periodic snapshot on Camera itself -- see
 * apps/cameras/detections.py on the backend for why these are separate. */
export interface CameraDetections {
  person_count: number;
  inference_ms: number;
  boxes: DetectionBox[];
  updated_at: string;
}

export interface TrackedBox {
  track_id: number;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  confidence: number;
}

/** Near-real-time tracking summary (Phase 4) -- a separate shape from
 * CameraDetections, not index-aligned with its `boxes`: tracking can carry a
 * recently-occluded track forward with no matching detection this tick. */
export interface CameraTracks {
  track_count: number;
  tracks: TrackedBox[];
  updated_at: string;
}

/** An entrance/exit line on one camera's frame (Phase 5, spec §4/§5).
 * Coordinates are pixels in the camera's own frame, at whatever resolution
 * the worker last reported -- see Camera.resolution_width/height. */
export interface Zone {
  id: string;
  camera: string;
  name: string;
  point_a_x: number;
  point_a_y: number;
  point_b_x: number;
  point_b_y: number;
  // A crossing from the negative side to the positive side of the directed
  // line point_a -> point_b counts as an entry when true, an exit when
  // false. Must agree with ai_worker/worker/zones.py::side_of_line's sign
  // convention -- see src/lib/zone-geometry.ts.
  entry_is_positive_side: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

/** One physical table's rectangle on a camera's frame (Phase 9, spec §10).
 * Axis-aligned, not a polygon -- see backend/apps/cameras/models.py's
 * TableZone docstring for why. Coordinates are pixels in the camera's own
 * frame, same convention as Zone above. */
export interface TableZone {
  id: string;
  camera: string;
  name: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export type TableSessionStatus = "active" | "ended";
export type TableReleaseReason = "" | "cleared" | "stale";

/** One continuous stretch of a table being occupied (spec §10). Read-only,
 * entirely derived -- see backend/apps/tables/projections.py. */
export interface TableSession {
  id: string;
  camera_id: string;
  table_zone_id: string;
  table_name: string;
  status: TableSessionStatus;
  occupied_at: string;
  released_at: string | null;
  release_reason: TableReleaseReason;
  // "Duration so far, as of the request" for an ACTIVE session -- a
  // snapshot, not a live value, same caveat as CustomerSession.duration_seconds.
  duration_seconds: number;
  created_at: string;
  updated_at: string;
}

/** GET /api/v1/tables/utilization/?start=&end= -- one entry per currently
 * configured table, even one with zero sessions in range. */
export interface TableUtilization {
  table_zone_id: string;
  table_name: string;
  camera_id: string;
  occupied_seconds: number;
  turnover_count: number;
  utilization_percent: number;
}

export type CustomerSessionStatus = "active" | "ended";
export type SessionExitReason = "" | "line_crossing" | "track_lost";

/** One customer's presence in a camera's frame, entry to exit (spec §5).
 * Read-only: entirely derived from the event pipeline, never created or
 * edited through the API -- see apps/sessions/projections.py on the backend. */
export interface CustomerSession {
  id: string;
  camera_id: string;
  track_id: number;
  status: CustomerSessionStatus;
  entry_at: string;
  entry_zone_name: string;
  exit_at: string | null;
  exit_zone_name: string;
  exit_reason: SessionExitReason;
  // "Duration so far, as of the request" for an ACTIVE session -- a
  // snapshot, not a live value. The dashboard ticks its own display from
  // entry_at between requests; see src/lib/duration.ts.
  duration_seconds: number;
  // Same snapshot caveat as duration_seconds -- Phase 6. The dashboard
  // recomputes this live from entry_at and the café's stay_color_stops
  // rather than polling for a fresh value every second; see
  // src/lib/stay-color.ts.
  color: string;
  created_at: string;
  updated_at: string;
}

/** One café-local calendar day's rollup (Phase 8, spec: "scheduled rollups
 * so a year of history does not mean a slow query"). Read-only, entirely
 * derived -- see backend/apps/analytics/rollups.py. `total_stay_seconds` and
 * `ended_session_count` travel alongside `average_stay_seconds` so a range
 * of days can be combined into a correctly-weighted average rather than a
 * naive average-of-averages; see src/lib/analytics.ts. */
export interface DailyStat {
  date: string; // YYYY-MM-DD, in the café's own timezone -- not UTC
  visitor_count: number;
  ended_session_count: number;
  total_stay_seconds: number;
  average_stay_seconds: number | null;
  longest_stay_seconds: number | null;
  // Entries bucketed by local hour-of-day, index 0-23.
  hourly_entries: number[];
  // True concurrent-occupancy peak that day, from a sweep over every
  // session's presence interval -- not the same thing as "the hour with the
  // most arrivals" (hourly_entries), and can genuinely differ.
  peak_occupancy: number;
  peak_occupancy_at: string | null;
  // False while the day is still in progress -- today's numbers are always
  // partial.
  is_final: boolean;
}

// --------------------------------------------------------------------------- #
// Public display (Phase 7) -- everything below is served unauthenticated from
// /api/v1/cafes/public/<slug>/... and ws/display/<slug>/. Deliberately
// separate shapes from the staff-facing types above, even where a field
// overlaps: the public payloads are their own serializers on the backend
// (apps/display/serializers.py), not a subset of an authenticated one.
// --------------------------------------------------------------------------- #

/** GET /api/v1/cafes/public/<slug>/ -- café branding plus what the display
 * needs to colour boxes and show occupancy. */
export interface PublicCafe {
  name: string;
  slug: string;
  logo: string | null;
  default_language: "en" | "fa";
  privacy_notice: string;
  stay_color_stops: ColorStop[];
  seating_capacity: number;
}

/** One synthetic dot -- position and colour only, never a bounding box or
 * raw video (see docs/architecture.md for why the display never streams
 * actual camera pixels). `entry_at` is null when this track has not (yet)
 * crossed a configured entry line -- still shown, coloured fresh, rather
 * than leaving a camera with no zone configured looking empty. */
export interface TrackedPerson {
  track_id: number;
  x: number;
  y: number;
  entry_at: string | null;
  color: string;
}

/** GET /api/v1/cafes/public/<slug>/live/ -- one entry per enabled camera
 * with a known resolution. */
export interface CameraLiveTracks {
  camera_id: string;
  camera_name: string;
  resolution_width: number;
  resolution_height: number;
  people: TrackedPerson[];
}

/** GET /api/v1/cafes/public/<slug>/stats/ -- durations only in
 * `leaderboard_seconds`, deliberately never a track id or camera name (see
 * apps/display/live.py::get_public_stats). */
export interface DisplayStats {
  occupancy: number;
  seating_capacity: number;
  visitors_today: number;
  average_stay_seconds: number | null;
  leaderboard_seconds: number[];
}

/** GET /api/v1/cafes/public/<slug>/messages/ -- pre-resolved to one
 * language; see apps/display/models.py::DisplayMessage.text. */
export interface PublicDisplayMessage {
  id: string;
  text: string;
}

/** Staff CRUD shape for /api/v1/display-messages/. */
export interface DisplayMessage {
  id: string;
  cafe: string;
  text_en: string;
  text_fa: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}
