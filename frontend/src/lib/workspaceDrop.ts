export type WorkspaceUploadItems = {
  files: { file: File; path: string }[]
  directories: string[]
}

export function workspaceFileSelection(files: File[]): WorkspaceUploadItems {
  return {
    files: files.map((file) => ({ file, path: file.webkitRelativePath || file.name })),
    directories: [],
  }
}

export async function readWorkspaceDrop(transfer: DataTransfer): Promise<WorkspaceUploadItems> {
  const sources = Array.from(transfer.items ?? [])
    .filter((item) => item.kind === 'file')
    .map((item) => ({
      entry: typeof item.webkitGetAsEntry === 'function' ? item.webkitGetAsEntry() : null,
      file: item.getAsFile(),
    }))
  if (sources.length === 0) return workspaceFileSelection(Array.from(transfer.files))

  const result: WorkspaceUploadItems = { files: [], directories: [] }
  const visit = async (entry: FileSystemEntry, parent: string): Promise<void> => {
    const path = parent ? `${parent}/${entry.name}` : entry.name
    if (entry.isFile) {
      const fileEntry = entry as FileSystemFileEntry
      const file = await new Promise<File>((resolve, reject) => {
        fileEntry.file(resolve, reject)
      })
      result.files.push({ file, path })
      return
    }
    if (!entry.isDirectory) throw new Error(`Tidak dapat membaca "${path}".`)
    const reader = (entry as FileSystemDirectoryEntry).createReader()
    let empty = true
    while (true) {
      const entries = await new Promise<FileSystemEntry[]>((resolve, reject) => {
        reader.readEntries(resolve, reject)
      })
      if (entries.length === 0) break
      empty = false
      for (const child of entries) await visit(child, path)
    }
    if (empty) result.directories.push(path)
  }

  for (const source of sources) {
    if (source.entry) await visit(source.entry, '')
    else if (source.file) result.files.push({ file: source.file, path: source.file.name })
    else throw new Error('Folder tidak dapat dibaca oleh browser. Coba tombol Unggah Folder.')
  }
  return result
}