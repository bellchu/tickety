/** Count Unicode code points, matching the API rather than textarea UTF-16 units. */
export function requirementTextBounds(text: string, maximum: number, minimum = 10) {
  const trimmed = text.trim();
  let length = 0;
  for (const _character of trimmed) length++;
  return { length, valid: length >= minimum && length <= maximum && !text.includes("\0") };
}
