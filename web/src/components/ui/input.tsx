"use client";

import * as React from "react";
import { motion } from "motion/react";
import { X, AlertCircle, CheckCircle2 } from "lucide-react";

import { cn } from "@/lib/utils";

export interface InputProps extends React.ComponentProps<"input"> {
  /** 显示字符计数 */
  showCount?: boolean;
  /** 最大字符数 */
  maxLength?: number;
  /** 实时校验函数 */
  validate?: (value: string) => string | undefined;
  /** 清空按钮 */
  clearable?: boolean;
  /** 左侧图标 */
  icon?: React.ReactNode;
  /** 右侧额外操作 */
  suffix?: React.ReactNode;
}

function Input({
  className,
  type,
  showCount = false,
  maxLength,
  validate,
  clearable = false,
  icon,
  suffix,
  value: controlledValue,
  onChange,
  ...props
}: InputProps) {
  const [internalValue, setInternalValue] = React.useState("");
  const [error, setError] = React.useState<string | undefined>();
  const [touched, setTouched] = React.useState(false);
  const [focused, setFocused] = React.useState(false);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const isControlled = controlledValue !== undefined;
  const value = isControlled ? String(controlledValue) : internalValue;

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newVal = e.target.value;
    if (!isControlled) setInternalValue(newVal);
    onChange?.(e);
    if (validate && touched) {
      setError(validate(newVal));
    }
  };

  const handleBlur = (e: React.FocusEvent<HTMLInputElement>) => {
    setTouched(true);
    setFocused(false);
    if (validate) {
      setError(validate(value));
    }
    props.onBlur?.(e);
  };

  const handleClear = () => {
    if (!isControlled) setInternalValue("");
    setError(undefined);
    if (inputRef.current) {
      inputRef.current.value = "";
      inputRef.current.focus();
    }
  };

  const errorId = props.id ? `${props.id}-error` : undefined;
  const countId = props.id ? `${props.id}-count` : undefined;

  return (
    <div className="relative">
      <div
        className={cn(
          "flex h-11 w-full min-w-0 items-center gap-2 rounded-2xl border bg-white/90 px-4 text-sm shadow-sm transition-all duration-200 outline-none",
          focused
            ? "border-stone-300 ring-[3px] ring-stone-200/80"
            : error && touched
              ? "border-red-300 ring-[3px] ring-red-200/60"
              : "border-input",
          icon && "pl-3",
          className,
        )}
        data-slot="input-wrapper"
      >
        {icon && <span className="flex-shrink-0 text-stone-400">{icon}</span>}
        <input
          ref={inputRef}
          type={type}
          value={isControlled ? controlledValue : undefined}
          onChange={handleChange}
          onFocus={(e) => { setFocused(true); props.onFocus?.(e); }}
          onBlur={handleBlur}
          data-slot="input"
          aria-invalid={error && touched ? "true" : undefined}
          aria-describedby={error && touched ? errorId : showCount ? countId : undefined}
          className="flex-1 bg-transparent text-stone-900 placeholder:text-stone-400 outline-none disabled:cursor-not-allowed disabled:opacity-50 file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium"
          maxLength={maxLength}
          {...props}
        />
        {clearable && value && (
          <button
            type="button"
            onClick={handleClear}
            className="flex-shrink-0 rounded-full p-0.5 text-stone-400 transition hover:bg-stone-100 hover:text-stone-600"
            tabIndex={-1}
          >
            <X className="size-3.5" />
          </button>
        )}
        {suffix && <span className="flex-shrink-0">{suffix}</span>}
        {error && touched && (
          <AlertCircle className="size-4 flex-shrink-0 text-red-500" />
        )}
        {validate && touched && !error && value && (
          <CheckCircle2 className="size-4 flex-shrink-0 text-emerald-500" />
        )}
      </div>
      {error && touched && (
        <motion.p
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          id={errorId}
          className="mt-1 px-2 text-xs text-red-500"
          role="alert"
        >
          {error}
        </motion.p>
      )}
      {showCount && maxLength && (
        <p
          id={countId}
          className={cn(
            "mt-1 text-right text-xs",
            value.length > maxLength * 0.9 ? "text-amber-500" : "text-stone-400",
          )}
        >
          {value.length}/{maxLength}
        </p>
      )}
    </div>
  );
}

export { Input };
