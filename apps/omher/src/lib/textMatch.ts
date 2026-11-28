// The one rule for the list searches over names and folders (the sidebar's bots and TERMINALS, Settings › Bots, the
// Apps page, Tasks): letter case is ignored and Unicode is compared composed (NFC). macOS hands a shell's folder and
// a file name over decomposed (NFD), so a Korean folder name typed in the search (composed) did not match the same
// name as the shell reported it. Lower-cased first, then composed: a few capitals lower-case into a letter and a
// combining mark, which composing puts back together.

/** `text` as every search here compares it. Callers key the typed search once and the fields they test with it. */
export const searchKey = (text: string): string => text.toLowerCase().normalize("NFC");

/** Whether any of `fields` holds `needle`, a `searchKey` (an empty needle matches everything). */
export function matchesSearch(needle: string, ...fields: (string | null | undefined)[]): boolean {
  return !needle || fields.some((f) => !!f && searchKey(f).includes(needle));
}
