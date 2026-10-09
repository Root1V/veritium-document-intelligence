import { AlertCircle, AlertTriangle, Info } from 'lucide-react'
import type { ValidationIssue } from '@/types/api'
import { Badge } from '@/components/ui/badge'
import { humanizeFieldName } from '@/lib/extraction'

const SEVERITY_ICON = {
  error: AlertCircle,
  warning: AlertTriangle,
  info: Info,
}

const SEVERITY_CLASSES = {
  error: 'text-red-600 dark:text-red-400',
  warning: 'text-amber-600 dark:text-amber-400',
  info: 'text-muted-foreground',
}

export function ValidationIssuesList({ issues }: { issues: ValidationIssue[] }) {
  if (issues.length === 0) {
    return <p className="text-sm text-muted-foreground">Sin observaciones de validación.</p>
  }

  return (
    <ul className="flex flex-col gap-3">
      {issues.map((issue, index) => {
        const Icon = SEVERITY_ICON[issue.severity]
        return (
          <li key={index} className="flex gap-3 rounded-lg border px-3 py-3">
            <Icon className={`mt-0.5 size-4 shrink-0 ${SEVERITY_CLASSES[issue.severity]}`} />
            <div className="flex flex-col gap-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="whitespace-pre-line text-sm font-medium">{issue.message}</span>
                <Badge variant="outline" className="text-xs">
                  {issue.category}
                </Badge>
                {issue.field_path && (
                  <Badge variant="outline" className="text-xs">
                    {humanizeFieldName(issue.field_path)}
                  </Badge>
                )}
              </div>
              <p className="text-xs text-muted-foreground">{issue.explanation}</p>
            </div>
          </li>
        )
      })}
    </ul>
  )
}
