export const GENRES = 'Genres', SESSIONS = 'Sessions', INBOX = '00 Inbox'

export function folderPath(kind: string, folder: string) {
  return { inbox: INBOX, rejected: '00 Rejected', genre: `${GENRES}/${folder}`, session: `${SESSIONS}/${folder}`,
    unsorted: folder === '(root)' ? '' : folder, '': '' }[kind] ?? ''
}
