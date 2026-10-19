export function PageHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex items-end justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold text-slate-100">{title}</h1>
        {description && <p className="mt-1 text-sm text-slate-400">{description}</p>}
      </div>
      {action}
    </div>
  );
}

export function Loading({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center py-16 text-sm text-slate-500">
      <span className="mr-2 inline-block h-3 w-3 animate-pulse rounded-full bg-slate-600" />
      {label}…
    </div>
  );
}

export function ErrorPanel({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div className="rounded-lg border border-red-900/60 bg-red-950/30 p-4">
      <p className="text-sm font-medium text-red-300">Request failed</p>
      <p className="mt-1 break-words text-sm text-red-200/80">{error}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded border border-red-800 px-3 py-1 text-xs text-red-200 hover:bg-red-900/40"
        >
          Retry
        </button>
      )}
    </div>
  );
}

export function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex items-center justify-center py-16 text-sm text-slate-500">{message}</div>
  );
}