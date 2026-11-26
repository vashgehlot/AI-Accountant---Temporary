// The same file again: the page skips a file it already has, and the API refuses one already saved or being read.
// Rows that may repeat each other are flagged by the API (possible_duplicate), where the AI sees them too.

// SHA-256 of a file's bytes as hex: the same content gives the same fingerprint, whatever its name.
// null when the browser cannot hash (crypto.subtle needs a secure context such as localhost).
export async function fingerprint(file: File): Promise<string | null> {
  try {
    const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer())
    return Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('')
  } catch {
    return null
  }
}
