import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { LoaderCircle, CheckCircle2, XCircle } from "lucide-react";

import { cn } from "@/lib/utils";
import { useInteractionFeedback } from "@/hooks/use-interaction-feedback";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-all disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4 shrink-0 [&_svg]:shrink-0 outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive",
  {
    variants: {
      variant: {
        default:
          "bg-primary text-primary-foreground shadow-xs hover:bg-primary/90",
        destructive:
          "bg-destructive text-white shadow-xs hover:bg-destructive/90 focus-visible:ring-destructive/20 dark:focus-visible:ring-destructive/40 dark:bg-destructive/60",
        outline:
          "border bg-background shadow-xs hover:bg-accent hover:text-accent-foreground dark:bg-input/30 dark:border-input dark:hover:bg-input/50",
        secondary:
          "bg-secondary text-secondary-foreground shadow-xs hover:bg-secondary/80",
        ghost:
          "hover:bg-accent hover:text-accent-foreground dark:hover:bg-accent/50",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-4 py-2 has-[>svg]:px-3",
        sm: "h-8 rounded-md gap-1.5 px-3 has-[>svg]:px-2.5",
        lg: "h-10 rounded-md px-6 has-[>svg]:px-4",
        icon: "size-9",
      },
      feedback: {
        true: "",
        false: "",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export type ButtonProps = React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
    /** 异步操作（自动显示 loading/success/error 三态） */
    action?: () => Promise<unknown>;
    /** 外部控制 loading */
    isLoading?: boolean;
    /** loading 文本 */
    loadingText?: string;
    /** 成功回调 */
    onSuccess?: (result: unknown) => void;
    /** 错误回调 */
    onError?: (error: Error) => void;
  };

function Button({
  className,
  variant,
  size,
  asChild = false,
  action,
  isLoading,
  loadingText,
  onSuccess,
  onError,
  children,
  onClick,
  disabled,
  ...props
}: ButtonProps) {
  const Comp = asChild ? Slot : "button";

  const { feedbackState, handleAction, feedbackStyles } = useInteractionFeedback({
    action,
    onSuccess,
    onError,
  });

  const loading = isLoading ?? feedbackState === "loading";
  const isSuccess = feedbackState === "success";
  const isError = feedbackState === "error";
  const isDisabled = disabled || loading || isSuccess || isError;

  const feedbackClass =
    isSuccess ? feedbackStyles.success
    : isError ? feedbackStyles.error
    : "";

  const handleClick = React.useCallback(
    (event: React.MouseEvent<HTMLButtonElement>) => {
      if (action) {
        void handleAction(event);
      } else {
        onClick?.(event);
      }
    },
    [action, handleAction, onClick],
  );

  const renderIcon = () => {
    if (loading) {
      return <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />;
    }
    if (isSuccess) {
      return <CheckCircle2 className="size-4 text-green-600" aria-hidden="true" />;
    }
    if (isError) {
      return <XCircle className="size-4 text-red-600" aria-hidden="true" />;
    }
    return null;
  };

  return (
    <Comp
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }), feedbackClass, "relative overflow-hidden")}
      disabled={isDisabled}
      onClick={handleClick}
      aria-busy={loading}
      {...props}
    >
      {renderIcon()}
      {loading && loadingText ? loadingText : children}
    </Comp>
  );
}

export { Button, buttonVariants };