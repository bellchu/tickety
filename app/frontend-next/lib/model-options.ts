export interface ModelOption {
  id: string;
  label: string;
}

export function filterModelOptions(
  options: readonly ModelOption[],
  query: string,
): ModelOption[] {
  const normalizedQuery = query.trim().toLowerCase();

  if (!normalizedQuery) {
    return [...options];
  }

  return options.filter(
    (option) =>
      option.id.toLowerCase().includes(normalizedQuery) ||
      option.label.toLowerCase().includes(normalizedQuery),
  );
}
