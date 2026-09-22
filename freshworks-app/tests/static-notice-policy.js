const forbiddenClientMarkup = [
  "<script",
  "{{{appclient}}}",
  "scripts/app.js",
];

export function hasForbiddenClientMarkup(markup) {
  const normalizedMarkup = markup.toLowerCase();
  return forbiddenClientMarkup.some((marker) => normalizedMarkup.includes(marker));
}
