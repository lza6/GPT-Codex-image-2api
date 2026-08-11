import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";

// ── 增强：堆叠管理 ────────────────────────────────────────────────

/** 管理所有已打开 Dialog 的堆叠顺序。 */
const dialogStack = new Set<string>();
let globalZIndex = 50;

function getNextZIndex() {
  globalZIndex += 1;
  return globalZIndex;
}

function Dialog(props: React.ComponentProps<typeof DialogPrimitive.Root>) {
  return <DialogPrimitive.Root data-slot="dialog" {...props} />;
}

function DialogTrigger(
  props: React.ComponentProps<typeof DialogPrimitive.Trigger>,
) {
  return <DialogPrimitive.Trigger data-slot="dialog-trigger" {...props} />;
}

function DialogPortal(
  props: React.ComponentProps<typeof DialogPrimitive.Portal>,
) {
  return <DialogPrimitive.Portal data-slot="dialog-portal" {...props} />;
}

function DialogClose(props: React.ComponentProps<typeof DialogPrimitive.Close>) {
  return <DialogPrimitive.Close data-slot="dialog-close" {...props} />;
}

function DialogOverlay({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Overlay>) {
  return (
    <DialogPrimitive.Overlay
      data-slot="dialog-overlay"
      className={cn(
        "data-[state=open]:animate-in data-[state=closed]:animate-out fixed inset-0 z-50 bg-black/30 backdrop-blur-[2px]",
        className,
      )}
      {...props}
    />
  );
}

// ── 增强：可拖拽 Dialog ──────────────────────────────────────────

interface DialogContentProps extends React.ComponentProps<typeof DialogPrimitive.Content> {
  showCloseButton?: boolean;
  /** 唯一标识，用于堆叠管理 */
  stackId?: string;
  /** 可拖拽 */
  draggable?: boolean;
}

function DialogContent({
  className,
  children,
  showCloseButton = true,
  stackId,
  draggable = false,
  ...props
}: DialogContentProps) {
  const [zIndex, setZIndex] = React.useState(50);
  const contentRef = React.useRef<HTMLDivElement>(null);
  const dragRef = React.useRef({ isDragging: false, startX: 0, startY: 0, offsetX: 0, offsetY: 0 });

  // 堆叠管理：打开时注册，关闭时移除
  React.useEffect(() => {
    if (stackId) {
      dialogStack.add(stackId);
      setZIndex(getNextZIndex());
    }
    return () => {
      if (stackId) dialogStack.delete(stackId);
    };
  }, [stackId]);

  // 点击时提升到最前
  const handlePointerDown = React.useCallback(() => {
    if (stackId) {
      setZIndex(getNextZIndex());
    }
  }, [stackId]);

  // 拖拽逻辑
  const handleDragStart = React.useCallback((e: React.PointerEvent) => {
    if (!draggable || !contentRef.current) return;
    dragRef.current.isDragging = true;
    dragRef.current.startX = e.clientX - dragRef.current.offsetX;
    dragRef.current.startY = e.clientY - dragRef.current.offsetY;
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  }, [draggable]);

  const handleDragMove = React.useCallback((e: React.PointerEvent) => {
    if (!dragRef.current.isDragging || !contentRef.current) return;
    const newX = e.clientX - dragRef.current.startX;
    const newY = e.clientY - dragRef.current.startY;
    dragRef.current.offsetX = newX;
    dragRef.current.offsetY = newY;
    contentRef.current.style.transform = `translate(calc(-50% + ${newX}px), calc(-50% + ${newY}px))`;
  }, []);

  const handleDragEnd = React.useCallback(() => {
    dragRef.current.isDragging = false;
  }, []);

  return (
    <DialogPortal>
      <DialogOverlay style={{ zIndex: zIndex - 1 }} />
      <DialogPrimitive.Content
        ref={contentRef}
        data-slot="dialog-content"
        style={stackId ? { zIndex } : undefined}
        onPointerDown={handlePointerDown}
        className={cn(
          "bg-background data-[state=open]:animate-in data-[state=closed]:animate-out fixed top-[50%] left-[50%] z-50 grid w-[min(92vw,560px)] translate-x-[-50%] translate-y-[-50%] gap-4 rounded-[28px] border border-white/80 p-6 shadow-[0_36px_120px_-45px_rgba(16,24,40,0.4)] duration-200",
          draggable && "cursor-grab active:cursor-grabbing",
          className,
        )}
        {...props}
      >
        {draggable && (
          <div
            className="absolute inset-x-0 top-0 h-8 cursor-grab rounded-t-[28px] active:cursor-grabbing"
            onPointerDown={handleDragStart}
            onPointerMove={handleDragMove}
            onPointerUp={handleDragEnd}
          />
        )}
        {children}
        {showCloseButton ? (
          <DialogPrimitive.Close className="ring-offset-background focus:ring-ring data-[state=open]:bg-accent data-[state=open]:text-muted-foreground absolute top-4 right-4 rounded-full p-1 opacity-70 transition-opacity hover:opacity-100 focus:ring-2 focus:outline-none disabled:pointer-events-none">
            <X className="size-4" />
            <span className="sr-only">Close</span>
          </DialogPrimitive.Close>
        ) : null}
      </DialogPrimitive.Content>
    </DialogPortal>
  );
}

function DialogHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="dialog-header"
      className={cn("flex flex-col gap-2 text-left", className)}
      {...props}
    />
  );
}

function DialogFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="dialog-footer"
      className={cn(
        "flex flex-col-reverse gap-2 sm:flex-row sm:justify-end",
        className,
      )}
      {...props}
    />
  );
}

function DialogTitle({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Title>) {
  return (
    <DialogPrimitive.Title
      data-slot="dialog-title"
      className={cn("text-xl leading-none font-semibold", className)}
      {...props}
    />
  );
}

function DialogDescription({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Description>) {
  return (
    <DialogPrimitive.Description
      data-slot="dialog-description"
      className={cn("text-muted-foreground text-sm", className)}
      {...props}
    />
  );
}

export {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
};