import * as React from "react";
import * as SelectPrimitive from "@radix-ui/react-select";
import { Check, ChevronDown, ChevronUp, Search, X } from "lucide-react";

import { cn } from "@/lib/utils";

function Select(props: React.ComponentProps<typeof SelectPrimitive.Root>) {
  return <SelectPrimitive.Root data-slot="select" {...props} />;
}

function SelectGroup(
  props: React.ComponentProps<typeof SelectPrimitive.Group>,
) {
  return <SelectPrimitive.Group data-slot="select-group" {...props} />;
}

function SelectValue(
  props: React.ComponentProps<typeof SelectPrimitive.Value>,
) {
  return <SelectPrimitive.Value data-slot="select-value" {...props} />;
}

function SelectTrigger({
  className,
  children,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Trigger>) {
  return (
    <SelectPrimitive.Trigger
      data-slot="select-trigger"
      className={cn(
        "border-input bg-background data-[placeholder]:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 flex h-11 w-full items-center justify-between gap-2 rounded-2xl border px-4 py-2 text-sm whitespace-nowrap shadow-sm outline-none focus-visible:ring-[3px] disabled:cursor-not-allowed disabled:opacity-50 [&>span]:line-clamp-1",
        className,
      )}
      {...props}
    >
      {children}
      <SelectPrimitive.Icon asChild>
        <ChevronDown className="size-4 opacity-60" />
      </SelectPrimitive.Icon>
    </SelectPrimitive.Trigger>
  );
}

function SelectScrollUpButton({
  className,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.ScrollUpButton>) {
  return (
    <SelectPrimitive.ScrollUpButton
      data-slot="select-scroll-up-button"
      className={cn(
        "flex cursor-default items-center justify-center py-1",
        className,
      )}
      {...props}
    >
      <ChevronUp className="size-4" />
    </SelectPrimitive.ScrollUpButton>
  );
}

function SelectScrollDownButton({
  className,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.ScrollDownButton>) {
  return (
    <SelectPrimitive.ScrollDownButton
      data-slot="select-scroll-down-button"
      className={cn(
        "flex cursor-default items-center justify-center py-1",
        className,
      )}
      {...props}
    >
      <ChevronDown className="size-4" />
    </SelectPrimitive.ScrollDownButton>
  );
}

function SelectContent({
  className,
  children,
  position = "popper",
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Content>) {
  return (
    <SelectPrimitive.Portal>
      <SelectPrimitive.Content
        data-slot="select-content"
        className={cn(
          "bg-popover text-popover-foreground data-[state=open]:animate-in data-[state=closed]:animate-out relative z-50 max-h-96 min-w-[8rem] overflow-x-hidden overflow-y-auto rounded-2xl border border-white/80 shadow-[0_20px_60px_-30px_rgba(15,23,42,0.35)]",
          position === "popper" &&
            "data-[side=bottom]:translate-y-1 data-[side=left]:-translate-x-1 data-[side=right]:translate-x-1 data-[side=top]:-translate-y-1",
          className,
        )}
        position={position}
        {...props}
      >
        <SelectScrollUpButton />
        <SelectPrimitive.Viewport
          className={cn(
            "p-1",
            position === "popper" &&
              "h-[var(--radix-select-trigger-height)] w-full min-w-[var(--radix-select-trigger-width)]",
          )}
        >
          {children}
        </SelectPrimitive.Viewport>
        <SelectScrollDownButton />
      </SelectPrimitive.Content>
    </SelectPrimitive.Portal>
  );
}

function SelectLabel({
  className,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Label>) {
  return (
    <SelectPrimitive.Label
      data-slot="select-label"
      className={cn("px-2 py-1.5 text-xs font-medium text-stone-500", className)}
      {...props}
    />
  );
}

function SelectItem({
  className,
  children,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Item>) {
  return (
    <SelectPrimitive.Item
      data-slot="select-item"
      className={cn(
        "focus:bg-accent focus:text-accent-foreground relative flex w-full cursor-default items-center gap-2 rounded-xl py-2 pr-8 pl-3 text-sm outline-none select-none data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
        className,
      )}
      {...props}
    >
      <span className="absolute right-2 flex size-4 items-center justify-center">
        <SelectPrimitive.ItemIndicator>
          <Check className="size-4" />
        </SelectPrimitive.ItemIndicator>
      </span>
      <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
    </SelectPrimitive.Item>
  );
}

function SelectSeparator({
  className,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Separator>) {
  return (
    <SelectPrimitive.Separator
      data-slot="select-separator"
      className={cn("bg-muted -mx-1 my-1 h-px", className)}
      {...props}
    />
  );
}

// ── 增强：搜索过滤下拉框 ──────────────────────────────────────────

export interface SearchableSelectProps {
  options: { value: string; label: string; group?: string }[];
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
  disabled?: boolean;
}

function SearchableSelect({
  options,
  value,
  onChange,
  placeholder = "选择...",
  className,
  disabled,
}: SearchableSelectProps) {
  const [open, setOpen] = React.useState(false);
  const [search, setSearch] = React.useState("");

  const filtered = React.useMemo(() => {
    if (!search) return options;
    const q = search.toLowerCase();
    return options.filter((o) => o.label.toLowerCase().includes(q) || o.value.toLowerCase().includes(q));
  }, [options, search]);

  const grouped = React.useMemo(() => {
    const groups: Record<string, { value: string; label: string }[]> = {};
    for (const opt of filtered) {
      const g = opt.group || "_default";
      if (!groups[g]) groups[g] = [];
      groups[g].push(opt);
    }
    return groups;
  }, [filtered]);

  const selectedLabel = options.find((o) => o.value === value)?.label || "";

  return (
    <div className="relative">
      <button
        type="button"
        className={cn(
          "border-input bg-background flex h-11 w-full items-center justify-between gap-2 rounded-2xl border px-4 py-2 text-sm shadow-sm outline-none transition disabled:cursor-not-allowed disabled:opacity-50",
          className,
        )}
        onClick={() => setOpen(!open)}
        disabled={disabled}
      >
        <span className={value ? "text-stone-900" : "text-stone-400"}>{value ? selectedLabel : placeholder}</span>
        <ChevronDown className={cn("size-4 opacity-60 transition", open && "rotate-180")} />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => { setOpen(false); setSearch(""); }} />
          <div className="bg-popover absolute left-0 right-0 top-full z-50 mt-1 max-h-72 overflow-hidden rounded-2xl border border-white/80 shadow-[0_20px_60px_-30px_rgba(15,23,42,0.35)]">
            <div className="flex items-center gap-2 border-b border-stone-100 px-3 py-2">
              <Search className="size-4 text-stone-400" />
              <input
                className="flex-1 bg-transparent text-sm outline-none placeholder:text-stone-400"
                placeholder="搜索..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                autoFocus
              />
              {search && (
                <button type="button" onClick={() => setSearch("")} className="text-stone-400 hover:text-stone-600">
                  <X className="size-3.5" />
                </button>
              )}
            </div>
            <div className="overflow-y-auto p-1" style={{ maxHeight: "240px" }}>
              {Object.entries(grouped).length === 0 ? (
                <p className="py-4 text-center text-xs text-stone-400">无匹配选项</p>
              ) : (
                Object.entries(grouped).map(([group, items]) => (
                  <div key={group}>
                    {group !== "_default" && (
                      <p className="px-2 py-1 text-[10px] font-medium uppercase tracking-wider text-stone-400">{group}</p>
                    )}
                    {items.map((opt) => (
                      <button
                        key={opt.value}
                        type="button"
                        className={cn(
                          "flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm transition hover:bg-stone-100",
                          opt.value === value && "bg-stone-50 font-medium text-stone-900",
                        )}
                        onClick={() => {
                          onChange(opt.value);
                          setOpen(false);
                          setSearch("");
                        }}
                      >
                        <span className="flex-1">{opt.label}</span>
                        {opt.value === value && <Check className="size-4 text-stone-900" />}
                      </button>
                    ))}
                  </div>
                ))
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
  SearchableSelect,
};