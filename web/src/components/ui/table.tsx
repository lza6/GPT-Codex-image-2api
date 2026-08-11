import * as React from "react";
import { motion, AnimatePresence } from "motion/react";

import { cn } from "@/lib/utils";

function Table({ className, ...props }: React.ComponentProps<"table">) {
  return <table className={cn("w-full caption-bottom text-sm", className)} {...props} />;
}

function TableHeader({ className, ...props }: React.ComponentProps<"thead">) {
  return <thead className={cn("border-b border-stone-100 text-[11px] tracking-[0.18em] text-stone-400 uppercase", className)} {...props} />;
}

function TableBody({ className, ...props }: React.ComponentProps<"tbody">) {
  return <tbody className={cn("[&_tr:last-child]:border-0", className)} {...props} />;
}

function TableRow({ className, ...props }: React.ComponentProps<"tr">) {
  return <tr className={cn("border-b border-stone-100 transition-colors hover:bg-stone-50/70", className)} {...props} />;
}

function TableHead({ className, ...props }: React.ComponentProps<"th">) {
  return <th className={cn("h-11 px-4 text-left align-middle font-medium", className)} {...props} />;
}

function TableCell({ className, ...props }: React.ComponentProps<"td">) {
  return <td className={cn("px-4 py-3 align-middle", className)} {...props} />;
}

// ── 增强：可展开行 ────────────────────────────────────────────────

interface ExpandableRowProps {
  /** 展开/折叠状态 */
  isOpen: boolean;
  /** 展开内容 */
  children: React.ReactNode;
  colSpan?: number;
  className?: string;
}

function ExpandableRowContent({ isOpen, children, colSpan, className }: ExpandableRowProps) {
  return (
    <AnimatePresence initial={false}>
      {isOpen && (
        <motion.tr
          key="expandable-content"
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: "auto", opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={{ duration: 0.2, ease: "easeInOut" }}
          className="overflow-hidden"
        >
          <td colSpan={colSpan} className={cn("px-4 py-0", className)}>
            <div className="py-3">{children}</div>
          </td>
        </motion.tr>
      )}
    </AnimatePresence>
  );
}

export { Table, TableBody, TableCell, TableHead, TableHeader, TableRow, ExpandableRowContent };