/**
 * 复制文本到剪贴板，兼容所有环境。
 *
 * http（非安全上下文，如纯 IP 直连）下 `navigator.clipboard` 为 `undefined`，
 * 裸调用 `navigator.clipboard.writeText` 会抛错导致页面崩溃
 * （"Cannot read properties of undefined (reading 'writeText')"）。
 * 这里统一做判空 + `execCommand("copy")` 兜底，保证任意环境都能复制。
 *
 * @returns 是否复制成功
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // clipboard 可用但被拒绝，走下面兜底
  }
  try {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    const ok = document.execCommand("copy");
    textarea.remove();
    return ok;
  } catch {
    return false;
  }
}