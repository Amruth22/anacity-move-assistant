export interface Community {
  id: string
  name: string
  city: string
  profile: string
  policies: Record<string, PolicyConfig>
}

export interface PolicyConfig {
  notice_days: number
  allowed_days: string[]
  hours: { start: string; end: string }
  blackout_dates: string[]
  deposit: { amount: number; currency: string; refundable: boolean; note?: string } | null
  elevator_booking: { required: boolean; note: string }
  documents: { id: string; name: string; required_for: string[] }[]
  custom_fields: { key: string; label: string; type: string; required: boolean }[]
}

export interface Resident {
  id: string
  name: string
  community_id: string
  unit_id: string
  unit_label: string
  tenancy: 'owner' | 'tenant'
}

export interface ChecklistItem {
  id: string
  name: string
  kind?: 'document' | 'task'
  done: boolean
  file?: {
    filename: string
    content_type: string
    size: number
    uploaded_at: string
  } | null
}

export interface ConfirmSummary {
  type: string
  unit: string
  requested_date: string
  time_window: string
  documents: string[]
  tasks: string[]
  deposit: { amount: number; currency: string } | null
}

export interface TimelineEvent {
  ts: string
  actor: string
  event: string
  note: string
}

export interface MoveRequest {
  id: string
  type: 'move_in' | 'move_out'
  resident_id: string
  resident_name: string
  tenancy: string
  community_id: string
  community_name: string
  unit_id: string
  unit_label: string
  requested_date: string
  time_window: string
  status: string
  checklist: ChecklistItem[]
  custom_fields: Record<string, unknown>
  notes: string
  timeline: TimelineEvent[]
  copilot: CopilotAssessment | null
}

export interface CopilotAssessment {
  summary: string
  policy_findings: { rule: string; status: 'pass' | 'fail' | 'warning'; detail: string }[]
  missing_items: string[]
  risk_flags: { severity: 'low' | 'medium' | 'high'; description: string }[]
  recommendation: 'approve' | 'reject' | 'request_more_info'
  reasoning: string
  suggested_message_to_resident: string
}

export type Persona =
  | { kind: 'resident'; resident: Resident; communityName: string }
  | { kind: 'admin' }
