import { Fragment, useEffect, useRef, type ReactNode } from 'react'
import { useInfiniteQuery } from '@tanstack/react-query'

import { ApiError, api } from '../lib/api'
import { useAuth } from '../lib/auth'
import type { FileNode } from '../lib/types'
import { IconChevron, IconRefresh } from './icons'

export default function WorkspaceDirectory({
  path,
  children,
}: {
  path: string
  children: (node: FileNode) => ReactNode
}) {
  const { user } = useAuth()
  const marker = useRef<HTMLDivElement>(null)
  const query = useInfiniteQuery({
    queryKey: ['workspace', 'directory', user?.id, path],
    queryFn: ({ pageParam }) => api.listWorkspaceDirectory(path, pageParam),
    initialPageParam: 0,
    getNextPageParam: (page) => page.next_offset ?? undefined,
    enabled: !!user,
    retry: false,
    refetchInterval: 30000,
    refetchOnWindowFocus: true,
  })
  const { hasNextPage, isFetching, isError, fetchNextPage } = query

  useEffect(() => {
    if (!marker.current || !hasNextPage || isFetching || isError || typeof IntersectionObserver === 'undefined')
      return
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting))
        void fetchNextPage({ cancelRefetch: false })
    })
    observer.observe(marker.current)
    return () => observer.disconnect()
  }, [hasNextPage, isFetching, isError, fetchNextPage])

  const nodes = [...new Map(
    (query.data?.pages.flatMap((page) => page.children) ?? []).map((node) => [node.path, node]),
  ).values()]

  return (
    <div className="min-w-0" data-workspace-directory={path}>
      {nodes.map((node) => <Fragment key={node.path}>{children(node)}</Fragment>)}
      {query.isPending && (
        <p role="status" className="px-2 py-3 text-xs text-slate-500">Memuat folder...</p>
      )}
      {query.isError && (
        <div role="alert" className="space-y-1 px-2 py-2 text-xs text-rose-600">
          <p>{query.error instanceof ApiError ? query.error.message : 'Gagal memuat folder.'}</p>
          <button
            type="button"
            className="btn-ghost min-h-8 px-2 py-1 text-xs"
            disabled={isFetching}
            onClick={() => void (query.isFetchNextPageError
              ? query.fetchNextPage({ cancelRefetch: false })
              : query.refetch())}
          >
            <IconRefresh className="h-3.5 w-3.5" />
            Coba lagi
          </button>
        </div>
      )}
      {!query.isPending && !query.isError && nodes.length === 0 && (
        <p className="px-2 py-3 text-xs text-slate-400">Folder kosong.</p>
      )}
      {hasNextPage && !query.isError && (
        <div ref={marker} className="min-h-8 px-2 py-1">
          <button
            type="button"
            className="btn-ghost min-h-8 w-full px-2 py-1 text-xs"
            disabled={isFetching}
            onClick={() => void fetchNextPage({ cancelRefetch: false })}
          >
            <IconChevron className="h-3.5 w-3.5 rotate-90" />
            {query.isFetchingNextPage ? 'Memuat...' : 'Muat berikutnya'}
          </button>
        </div>
      )}
    </div>
  )
}