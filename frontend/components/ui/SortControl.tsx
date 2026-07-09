export type SortDirection = "asc" | "desc";

export type SortOption = {
  value: string;
  label: string;
};

type SortControlProps = {
  fields: SortOption[];
  sortBy: string;
  sortDir: SortDirection;
  onSortByChange: (value: string) => void;
  onSortDirChange: (value: SortDirection) => void;
  disabled?: boolean;
};

const selectClass =
  "rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 outline-none ring-slate-400 focus:ring-2 disabled:cursor-not-allowed disabled:bg-slate-50";

export function SortControl({
  fields,
  sortBy,
  sortDir,
  onSortByChange,
  onSortDirChange,
  disabled = false,
}: SortControlProps) {
  return (
    <div className="flex items-center gap-2">
      <label htmlFor="sort-by" className="sr-only">
        Sort by
      </label>
      <select
        id="sort-by"
        value={sortBy}
        onChange={(e) => onSortByChange(e.target.value)}
        disabled={disabled}
        className={selectClass}
      >
        {fields.map((field) => (
          <option key={field.value} value={field.value}>
            Sort: {field.label}
          </option>
        ))}
      </select>
      <label htmlFor="sort-dir" className="sr-only">
        Sort direction
      </label>
      <select
        id="sort-dir"
        value={sortDir}
        onChange={(e) => onSortDirChange(e.target.value as SortDirection)}
        disabled={disabled}
        className={selectClass}
      >
        <option value="asc">Ascending</option>
        <option value="desc">Descending</option>
      </select>
    </div>
  );
}
