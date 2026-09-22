/** Locate one exact quotation and its neighbors without rendering every match. */
export function locateEvidenceQuote(content: string, quote: string, selected?: number) {
  const first = quote ? content.indexOf(quote) : -1;
  if (first < 0) return { position: -1, previous: -1, next: -1 };
  const position = selected !== undefined && Number.isInteger(selected) && selected >= 0 && content.startsWith(quote, selected) ? selected : first;
  return {
    position,
    previous: position > 0 ? content.lastIndexOf(quote, position - 1) : -1,
    next: content.indexOf(quote, position + 1),
  };
}
