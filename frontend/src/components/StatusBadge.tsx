const LABELS: Record<string, string> = {
  submitted: 'Submitted',
  needs_info: 'Needs info',
  approved: 'Approved',
  rejected: 'Rejected',
  completed: 'Completed',
  cancelled: 'Cancelled',
}

export default function StatusBadge({ status }: { status: string }) {
  return <span className={`status-badge ${status}`}>{LABELS[status] ?? status}</span>
}
